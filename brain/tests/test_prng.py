from binbrain.prng import Prng


def test_xorshift32_matches_the_firmware_algorithm():
    # Worked by hand from firmware/TrashBotWeb/src/core/prng.h for seed 1:
    #   x ^= x << 13  -> 8193
    #   x ^= x >> 17  -> 8193
    #   x ^= x << 5   -> 270369
    r = Prng(1)
    assert r.next() == 270369


def test_zero_seed_does_not_lock_up():
    r = Prng(0)
    assert r.initial_seed == 0x2A2A2A2A
    assert r.next() != 0


def test_same_seed_same_sequence():
    a, b = Prng(0x9F3A1C22), Prng(0x9F3A1C22)
    assert [a.next() for _ in range(100)] == [b.next() for _ in range(100)]


def test_helpers_stay_in_range():
    r = Prng(7)
    for _ in range(2000):
        assert 0 <= r.pick(5) < 5
        assert -3 <= r.range(-3, 3) <= 3
        assert 0.0 <= r.uniform() < 1.0
    assert r.range(4, 4) == 4
    assert r.chance(0) is False and r.chance(100) is True
