# Engineering Capability Design

Use this reference when the engineering exploration is about designing a feature module, service capability, workflow, integration, API-backed operation, plugin, tool, Skill, or enterprise capability.

## Core Principle

An engineering capability is not just a block of code. It should have a clear boundary, a reliable interface, predictable behavior, observable outcomes, and governance appropriate to its risk.

For ordinary product work, this often means a feature module or service operation. For agent systems, it may mean a tool, plugin, workflow, or Skill. Use the same design discipline, but scale the detail to the risk and complexity of the capability.

## Standard Layers

Design only the layers that matter for the requested capability, but consider each one:

- Purpose and boundary: what the module or capability owns, what it does not own, and who calls it.
- Interface: inputs, outputs, required fields, validation, serialization, and caller expectations.
- Execution: control flow, dependencies, side effects, retry behavior, result formatting, and idempotency.
- State and context: user/session context, environment context, persisted state, cache, history, and configuration.
- Permission and security: authorization, least privilege, data exposure, secrets, PII, unsafe actions, and abuse paths.
- Observability: logs, metrics, traces, audit events, latency, error type, and business events.
- Error handling: validation errors, dependency failures, timeouts, permission errors, conflict states, and internal errors.
- Evaluation: functional correctness, task completion, user experience, performance, and business impact where relevant.
- Lifecycle: design, implement, test, release, monitor, version, migrate, deprecate, and remove.

## Declarative Plus Runtime Pattern

For configurable or reusable capabilities, prefer a declarative contract plus a runtime executor:

```yaml
name: capability_name
version: 0.1.0
description: What this capability does and when to use it.
inputs:
  type: object
outputs:
  type: object
permissions:
  - read
policies:
  timeout_ms: 30000
  idempotent: true
observability:
  log_fields:
    - latency_ms
    - tool_calls
    - error_type
```

The runtime should validate input, execute the smallest necessary flow, handle known failures, and return a structured result. For a normal feature module, this contract may live as route definitions, service types, DTOs, schemas, or module documentation instead of a standalone YAML file.

## Design Output Shape

When asked to design a capability, produce:

- capability name and purpose
- ownership boundary and non-goals
- callers, triggers, or routing conditions
- input and output contract
- execution and data flow
- state, persistence, and context needs
- permissions and safety boundaries
- observability and error model
- test and acceptance criteria
- lifecycle, migration, and versioning notes
