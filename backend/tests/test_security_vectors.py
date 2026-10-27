"""
Security Vector Pytest Suite for Attack Simulation (Issue #10).

Simulates high-severity adversarial scenarios:
1. Cliff Bypass Attempts (attempting withdrawal before cliff threshold & unauthorized third-party withdrawal)
2. Double-Withdraw Race Conditions (concurrent asyncio.gather reentrancy & repeated zero-balance draining)
3. Integer Overflow, Zero/Negative Amount & Time Distortion Boundaries
4. Unauthorized Revocation & Tampering of Non-Revocable Escrows
5. Double Cancellation & Post-Cancellation Drain Attacks
"""

import asyncio
import time

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models import init_db


@pytest.fixture(autouse=True)
def setup_database():
    init_db()


@pytest.mark.asyncio
async def test_attack_cliff_bypass_attempt():
    """
    ATTACK VECTOR 1: Cliff Bypass & Unauthorized Withdrawal Simulation.
    An adversary attempts to invoke token withdrawal when the ledger timestamp
    is strictly before the cliff timestamp, or from an unauthorized third-party
    signer. The protocol must return 0 unlocked tokens and reject premature
    withdrawal with HTTP 400 and unauthorized actors with HTTP 403.
    """
    now = int(time.time())
    sender = "GADV3RSARYSENDER777777777777777777777777777777777777777777"
    recipient = "GADV3RSARYRECIPIENT888888888888888888888888888888888888888"
    attacker = "GMALICIOUSTHIRDPARTY9999999999999999999999999999999999999"
    payload = {
        "sender": sender,
        "recipient": recipient,
        "token": "CDLZFC3SYJYDZT7K67VZ75HPJVIEUVNIXF47ZG2FB2RMQQVU2HHGCYSC",
        "amount": 50_000_0000000,
        "start_time": now,
        "cliff_time": now + 86400,      # Cliff 24 hours in the future
        "end_time": now + 86400 * 30,   # Stream ends in 30 days
        "revocable": True,
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/api/streams", json=payload)
        assert res.status_code == 201
        stream_id = res.json()["id"]

        # Check that claimable amount is strictly zero before cliff
        stream_view = await ac.get(f"/api/streams/{stream_id}")
        assert stream_view.status_code == 200
        assert stream_view.json()["unlocked_amount"] == 0
        assert stream_view.json()["claimable_amount"] == 0
        assert stream_view.json()["status"] == "cliff_pending"

        # Attempt premature withdraw by recipient
        attack_res = await ac.post(f"/api/streams/{stream_id}/withdraw?actor={recipient}")
        assert attack_res.status_code == 400
        assert "No unlocked tokens" in attack_res.json()["detail"]

        # Attempt unauthorized withdrawal by third-party attacker
        unauth_res = await ac.post(f"/api/streams/{stream_id}/withdraw?actor={attacker}")
        assert unauth_res.status_code == 403
        assert "Unauthorized" in unauth_res.json()["detail"]


@pytest.mark.asyncio
async def test_attack_double_withdraw_race():
    """
    ATTACK VECTOR 2: Double-Withdraw / Concurrent Race Condition Simulation.
    An attacker dispatches rapid, concurrent withdrawal requests via asyncio.gather
    to claim unlocked balances more than once before state persistence settles.
    Total claimed stroops must never exceed total_amount.
    """
    now = int(time.time())
    total_amount = 20_000_0000000
    payload = {
        "sender": "GAHONESTSENDER1111111111111111111111111111111111111111111",
        "recipient": "GGREEDYATTACKER222222222222222222222222222222222222222222",
        "token": "CDLZFC3SYJYDZT7K67VZ75HPJVIEUVNIXF47ZG2FB2RMQQVU2HHGCYSC",
        "amount": total_amount,
        "start_time": now - 100,
        "cliff_time": now - 50,
        "end_time": now - 10,  # Stream fully vested in the past
        "revocable": True,
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/api/streams", json=payload)
        assert res.status_code == 201
        stream_id = res.json()["id"]

        # Fire 5 concurrent withdrawal requests simultaneously
        responses = await asyncio.gather(
            ac.post(f"/api/streams/{stream_id}/withdraw"),
            ac.post(f"/api/streams/{stream_id}/withdraw"),
            ac.post(f"/api/streams/{stream_id}/withdraw"),
            ac.post(f"/api/streams/{stream_id}/withdraw"),
            ac.post(f"/api/streams/{stream_id}/withdraw"),
        )

        status_codes = [r.status_code for r in responses]
        assert status_codes.count(200) == 1
        assert status_codes.count(400) == 4

        # Verify final stream state has exact total_amount claimed and 0 remaining
        final_view = await ac.get(f"/api/streams/{stream_id}")
        assert final_view.status_code == 200
        assert final_view.json()["claimed_amount"] == total_amount
        assert final_view.json()["claimable_amount"] == 0

        # Sequential follow-up withdrawal must also fail with HTTP 400
        claim_after = await ac.post(f"/api/streams/{stream_id}/withdraw")
        assert claim_after.status_code == 400
        assert "No unlocked tokens" in claim_after.json()["detail"]


@pytest.mark.asyncio
async def test_attack_integer_overflow_and_time_distortion():
    """
    ATTACK VECTOR 3: Time Distortion, Zero/Negative Amounts & Boundary Precision.
    Attempts creation with corrupted or negative parameters:
    - negative or 0 amounts (rejected with HTTP 422)
    - start_time > cliff_time (rejected with HTTP 400)
    - cliff_time >= end_time (rejected with HTTP 400)
    - High-value stroop stream (10^15 stroops) verifying exact integer math without float drift.
    """
    now = int(time.time())
    sender = "GA1111111111111111111111111111111111111111111111111111111"
    recipient = "GB2222222222222222222222222222222222222222222222222222222"
    token = "CDLZFC3SYJYDZT7K67VZ75HPJVIEUVNIXF47ZG2FB2RMQQVU2HHGCYSC"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Negative amount
        res_neg = await ac.post("/api/streams", json={
            "sender": sender,
            "recipient": recipient,
            "token": token,
            "amount": -5000,
            "start_time": now,
            "cliff_time": now + 10,
            "end_time": now + 20,
            "revocable": True,
        })
        assert res_neg.status_code == 422

        # Zero amount
        res_zero = await ac.post("/api/streams", json={
            "sender": sender,
            "recipient": recipient,
            "token": token,
            "amount": 0,
            "start_time": now,
            "cliff_time": now + 10,
            "end_time": now + 20,
            "revocable": True,
        })
        assert res_zero.status_code == 422

        # Time distortion: start_time > cliff_time
        res_start_gt_cliff = await ac.post("/api/streams", json={
            "sender": sender,
            "recipient": recipient,
            "token": token,
            "amount": 1000,
            "start_time": now + 50,
            "cliff_time": now + 10,
            "end_time": now + 100,
            "revocable": True,
        })
        assert res_start_gt_cliff.status_code == 400
        assert "Invalid bounds" in res_start_gt_cliff.json()["detail"]

        # Time distortion: cliff_time >= end_time
        res_cliff_ge_end = await ac.post("/api/streams", json={
            "sender": sender,
            "recipient": recipient,
            "token": token,
            "amount": 1000,
            "start_time": now,
            "cliff_time": now + 100,
            "end_time": now + 100,
            "revocable": True,
        })
        assert res_cliff_ge_end.status_code == 400
        assert "Invalid bounds" in res_cliff_ge_end.json()["detail"]

        # Large institutional allocation (10^15 stroops = 100,000,000 tokens)
        whale_amount = 1_000_000_000_000_000
        res_whale = await ac.post("/api/streams", json={
            "sender": sender,
            "recipient": recipient,
            "token": token,
            "amount": whale_amount,
            "start_time": now - 200,
            "cliff_time": now - 100,
            "end_time": now - 10,
            "revocable": False,
        })
        assert res_whale.status_code == 201
        assert res_whale.json()["unlocked_amount"] == whale_amount
        assert res_whale.json()["claimable_amount"] == whale_amount


@pytest.mark.asyncio
async def test_attack_illegal_cancel_and_double_cancel():
    """
    ATTACK VECTOR 4: Illegal Cancellation & Unauthorized Revocation.
    - Sender attempts to cancel an immutable non-revocable stream -> HTTP 400.
    - An attacker (not sender) attempts to cancel a revocable stream -> HTTP 403.
    - Recipient attempts to cancel sender's revocable stream -> HTTP 403.
    """
    now = int(time.time())
    honest_sender = "GAHONEST11111111111111111111111111111111111111111111111111"
    recipient = "GBRECIP222222222222222222222222222222222222222222222222222"
    attacker = "GAATTACKER99999999999999999999999999999999999999999999999"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Create non-revocable stream
        res_nonrev = await ac.post("/api/streams", json={
            "sender": honest_sender,
            "recipient": recipient,
            "token": "CDLZFC3SYJYDZT7K67VZ75HPJVIEUVNIXF47ZG2FB2RMQQVU2HHGCYSC",
            "amount": 50000000,
            "start_time": now - 10,
            "cliff_time": now - 5,
            "end_time": now + 100,
            "revocable": False,
        })
        nonrev_id = res_nonrev.json()["id"]

        # Cancel attempt on non-revocable stream
        res_cancel_nonrev = await ac.post(f"/api/streams/{nonrev_id}/cancel?sender={honest_sender}")
        assert res_cancel_nonrev.status_code == 400
        assert "not revocable" in res_cancel_nonrev.json()["detail"]

        # Create revocable stream
        res_rev = await ac.post("/api/streams", json={
            "sender": honest_sender,
            "recipient": recipient,
            "token": "CDLZFC3SYJYDZT7K67VZ75HPJVIEUVNIXF47ZG2FB2RMQQVU2HHGCYSC",
            "amount": 50000000,
            "start_time": now - 10,
            "cliff_time": now - 5,
            "end_time": now + 100,
            "revocable": True,
        })
        rev_id = res_rev.json()["id"]

        # External attacker attempts cancellation
        res_unauth = await ac.post(f"/api/streams/{rev_id}/cancel?sender={attacker}")
        assert res_unauth.status_code == 403
        assert "Unauthorized" in res_unauth.json()["detail"]

        # Recipient attempts to self-cancel to trigger refund split manipulation
        res_recip_cancel = await ac.post(f"/api/streams/{rev_id}/cancel?sender={recipient}")
        assert res_recip_cancel.status_code == 403
        assert "Unauthorized" in res_recip_cancel.json()["detail"]


@pytest.mark.asyncio
async def test_attack_double_cancellation_and_post_cancel_withdraw():
    """
    ATTACK VECTOR 5: Double Cancellation & Post-Cancellation Drain Attack.
    - Legitimate sender cancels an active revocable stream -> HTTP 200.
    - Sender attempts a second cancellation to double-claim refund -> HTTP 400.
    - Recipient attempts to withdraw additional tokens after cancellation -> HTTP 400.
    """
    now = int(time.time())
    honest_sender = "GAHONEST11111111111111111111111111111111111111111111111111"
    recipient = "GBRECIP222222222222222222222222222222222222222222222222222"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res_rev = await ac.post("/api/streams", json={
            "sender": honest_sender,
            "recipient": recipient,
            "token": "CDLZFC3SYJYDZT7K67VZ75HPJVIEUVNIXF47ZG2FB2RMQQVU2HHGCYSC",
            "amount": 100_000_000,
            "start_time": now - 50,
            "cliff_time": now - 25,
            "end_time": now + 50,
            "revocable": True,
        })
        assert res_rev.status_code == 201
        rev_id = res_rev.json()["id"]

        # First legitimate cancellation succeeds and settles unlocked balance
        res_legit = await ac.post(f"/api/streams/{rev_id}/cancel?sender={honest_sender}")
        assert res_legit.status_code == 200
        cancelled_state = res_legit.json()
        assert cancelled_state["is_cancelled"] is True
        assert cancelled_state["status"] == "cancelled"
        assert cancelled_state["claimable_amount"] == 0

        # Second cancel attempt must fail with HTTP 400
        res_double = await ac.post(f"/api/streams/{rev_id}/cancel?sender={honest_sender}")
        assert res_double.status_code == 400
        assert "already cancelled" in res_double.json()["detail"]

        # Post-cancellation withdrawal attempt must fail with HTTP 400
        res_post_withdraw = await ac.post(f"/api/streams/{rev_id}/withdraw?actor={recipient}")
        assert res_post_withdraw.status_code == 400
        assert "No unlocked tokens" in res_post_withdraw.json()["detail"]
