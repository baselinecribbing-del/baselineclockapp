#!/usr/bin/env python3
from app.services.bootstrap_admin_service import (
    bootstrap_owner_admin_account,
    get_bootstrap_admin_config,
)


def main() -> int:
    result = bootstrap_owner_admin_account()

    if result.status == "created":
        print("Bootstrap owner account created.")
        print(f"company_id={result.company_id}")
        print(f"username={result.username}")
        print(f"email={result.email}")
        if result.password:
            print(f"password={result.password}")
        return 0

    config = get_bootstrap_admin_config()
    if result.reason == "existing_user_accounts_present" and config is not None:
        print("Bootstrap owner account already exists or the system has already been initialized.")
        print(f"company_id={config.company_id}")
        print(f"username={config.username}")
        print(f"email={config.email}")
        return 0

    print(f"Bootstrap owner account not created: {result.reason or 'unknown'}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
