"""pytest 없이 테스트를 실행하는 러너.

사용:  python -m autotrader.run_tests
"""
from __future__ import annotations

import traceback

from . import tests as T


def main() -> int:
    fns = [getattr(T, n) for n in dir(T) if n.startswith("test_")]
    passed = 0
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
            passed += 1
        except Exception:
            print(f"  ✗ {fn.__name__}")
            traceback.print_exc()
            failed += 1
    print(f"\n결과: {passed} passed, {failed} failed (총 {passed + failed})")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
