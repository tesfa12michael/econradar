"""Modal-deployed inference functions (architecture decision #21).

Deliberately isolated from the rest of the backend: nothing in this package may
import `config`, `db`, `models` or any other application module. Modal mounts and
executes this code remotely, and the boundary that keeps decision #21 true —
**Modal computes, it never persists** — is enforced by that isolation. A remote
function that cannot import the database layer cannot write to it.

The package is named `modal_app`, not `modal`, so it never shadows the SDK.
"""
