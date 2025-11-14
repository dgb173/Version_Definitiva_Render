from __future__ import annotations

import sys


def main() -> int:
    """
    Minimal stub that satisfies `playwright` CLI invocations during deployments.
    It just logs the received arguments and exits successfully so the build
    pipeline can continue even when Playwright is unavailable.
    """
    args = sys.argv[1:]
    joined_args = " ".join(args) if args else "(sin argumentos)"
    print("[render-playwright-stub] Playwright no es necesario en este despliegue.")
    print(f"[render-playwright-stub] Comando recibido: {joined_args}")
    print("[render-playwright-stub] Se omite la instalacion de navegadores.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
