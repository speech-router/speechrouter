from speechrouter_gateway.router.limits import ConcurrencyGuard


def test_cap_enforced_per_scope():
    guard = ConcurrencyGuard(limit=2)
    assert guard.acquire("org1")
    assert guard.acquire("org1")
    assert not guard.acquire("org1")  # third stream rejected
    assert guard.acquire("org2")  # other orgs unaffected


def test_release_frees_slots_and_never_goes_negative():
    guard = ConcurrencyGuard(limit=1)
    assert guard.acquire("o")
    guard.release("o")
    assert guard.acquire("o")
    guard.release("o")
    guard.release("o")  # double-release safe
    assert guard.active("o") == 0
    assert guard.acquire("o")


def test_zero_means_unlimited():
    guard = ConcurrencyGuard(limit=0)
    for _ in range(100):
        assert guard.acquire("o")
