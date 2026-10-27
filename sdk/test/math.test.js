const assert = require('assert');
const { calculateVesting, formatStroops, parseTokensToStroops } = require('../dist/math');

console.log('Testing @sorostream/sdk vesting math...');

const stream = {
  totalAmount: BigInt(100_000_000), // 10 tokens
  claimedAmount: BigInt(0),
  startTime: 1000,
  cliffTime: 2000,
  endTime: 6000,
  isCancelled: false,
};

// 1. Before cliff (t = 1500)
const beforeCliff = calculateVesting(stream, 1500);
assert.strictEqual(beforeCliff.unlockedAmount, BigInt(0));
assert.strictEqual(beforeCliff.claimableAmount, BigInt(0));
assert.strictEqual(beforeCliff.status, 'cliff_pending');

// 2. At cliff (t = 2000): (2000 - 1000) / 5000 = 20%
const atCliff = calculateVesting(stream, 2000);
assert.strictEqual(atCliff.unlockedAmount, BigInt(20_000_000));
assert.strictEqual(atCliff.claimableAmount, BigInt(20_000_000));
assert.strictEqual(atCliff.unlockedPercentage, 20.0);
assert.strictEqual(atCliff.status, 'active');

// 3. At midpoint (t = 3500): (3500 - 1000) / 5000 = 50%
const atMidpoint = calculateVesting(stream, 3500);
assert.strictEqual(atMidpoint.unlockedAmount, BigInt(50_000_000));
assert.strictEqual(atMidpoint.claimableAmount, BigInt(50_000_000));

// 4. Past end (t = 7000): 100% unlocked
const pastEnd = calculateVesting(stream, 7000);
assert.strictEqual(pastEnd.unlockedAmount, BigInt(100_000_000));
assert.strictEqual(pastEnd.claimableAmount, BigInt(100_000_000));
assert.strictEqual(pastEnd.status, 'active');

// 5. Completed stream (100% unlocked and 100% claimed)
const completedStream = calculateVesting(
  { ...stream, claimedAmount: BigInt(100_000_000) },
  7000
);
assert.strictEqual(completedStream.claimableAmount, BigInt(0));
assert.strictEqual(completedStream.status, 'completed');

// 6. Cancelled stream freezes unlocked at claimedAmount
const cancelledStream = calculateVesting(
  { ...stream, claimedAmount: BigInt(30_000_000), isCancelled: true },
  3500
);
assert.strictEqual(cancelledStream.unlockedAmount, BigInt(30_000_000));
assert.strictEqual(cancelledStream.claimableAmount, BigInt(0));
assert.strictEqual(cancelledStream.status, 'cancelled');

// 7. Stroop conversion helpers
assert.strictEqual(formatStroops(BigInt(125_000_000), 7, 2), '12.50');
assert.strictEqual(parseTokensToStroops('12.5', 7), BigInt(125_000_000));

console.log('All @sorostream/sdk math unit tests passed!');
