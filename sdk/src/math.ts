import { StreamCalculation, StreamRecord, StreamStatus } from './types';

/**
 * Calculates real-time linear vesting math matching the Soroban smart contract.
 *
 * Linear Formula:
 * • If t < cliffTime: Unlocked = 0
 * • If t >= endTime: Unlocked = totalAmount
 * • Otherwise: Unlocked = totalAmount * (t - startTime) / (endTime - startTime)
 * Claimable = max(0, Unlocked - claimedAmount)
 */
export function calculateVesting(
  record: Pick<StreamRecord, 'totalAmount' | 'claimedAmount' | 'startTime' | 'cliffTime' | 'endTime' | 'isCancelled'>,
  currentTimestamp: number = Math.floor(Date.now() / 1000)
): StreamCalculation {
  const { totalAmount, claimedAmount, startTime, cliffTime, endTime, isCancelled } = record;
  const t = currentTimestamp;

  let unlockedAmount: bigint;
  let claimableAmount: bigint;
  let status: StreamStatus;

  if (isCancelled) {
    unlockedAmount = claimedAmount;
    claimableAmount = BigInt(0);
    status = 'cancelled';
  } else if (t < cliffTime) {
    unlockedAmount = BigInt(0);
    claimableAmount = BigInt(0);
    status = 'cliff_pending';
  } else if (t >= endTime) {
    unlockedAmount = totalAmount;
    claimableAmount = unlockedAmount > claimedAmount ? unlockedAmount - claimedAmount : BigInt(0);
    status = claimableAmount === BigInt(0) ? 'completed' : 'active';
  } else {
    const elapsed = BigInt(Math.max(0, t - startTime));
    const duration = BigInt(Math.max(1, endTime - startTime));
    unlockedAmount = (totalAmount * elapsed) / duration;
    claimableAmount = unlockedAmount > claimedAmount ? unlockedAmount - claimedAmount : BigInt(0);
    status = 'active';
  }

  const totalNum = Number(totalAmount);
  const unlockedNum = Number(unlockedAmount);
  const claimedNum = Number(claimedAmount);

  const unlockedPercentage = totalNum > 0 ? Number(((unlockedNum / totalNum) * 100).toFixed(2)) : 0;
  const claimedPercentage = totalNum > 0 ? Number(((claimedNum / totalNum) * 100).toFixed(2)) : 0;

  const totalDuration = Math.max(1, endTime - startTime);
  const ratePerSecond = totalNum / totalDuration;
  const ratePerDay = ratePerSecond * 86400;

  return {
    currentTime: t,
    unlockedAmount,
    claimableAmount,
    unlockedPercentage,
    claimedPercentage,
    ratePerSecond: Number(ratePerSecond.toFixed(4)),
    ratePerDay: Number(ratePerDay.toFixed(2)),
    status,
  };
}

/**
 * Formats a raw integer stroop/smallest-unit balance into a fixed-precision decimal string.
 */
export function formatStroops(
  amount: bigint,
  decimals: number = 7,
  precision: number = 2
): string {
  const divisor = 10 ** decimals;
  return (Number(amount) / divisor).toFixed(precision);
}

/**
 * Converts a human-readable token amount into raw on-chain integer units (stroops).
 */
export function parseTokensToStroops(
  amountTokens: number | string,
  decimals: number = 7
): bigint {
  const numAmount = typeof amountTokens === 'string' ? parseFloat(amountTokens) : amountTokens;
  if (isNaN(numAmount) || numAmount <= 0) {
    throw new Error(`Stream amount must be greater than 0, received: ${amountTokens}`);
  }
  const multiplier = BigInt(10 ** decimals);
  const whole = BigInt(Math.floor(numAmount));
  const fraction = numAmount - Math.floor(numAmount);
  const fractionBigInt = BigInt(Math.round(fraction * 10 ** decimals));
  return whole * multiplier + fractionBigInt;
}
