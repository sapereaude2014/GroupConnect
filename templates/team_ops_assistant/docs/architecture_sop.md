# Engineering Architecture Review SOP

## 1. Design Principles
- **Decoupled Architecture**: Core domain logic must remain independent of messaging channels and external transport protocols.
- **Fail-Safe Defaults**: Security policies must default to Deny/Lockdown when unconfigured.
- **Subprocess Isolation**: External CLI agent executions must run in isolated POSIX process groups to permit clean `/stop` termination.

## 2. PR Review Checklist
- [ ] Zero hardcoded secrets, private tokens, or host-specific paths.
- [ ] Unit tests added with > 90% code path coverage.
- [ ] Full backward compatibility with existing configuration keys.
