# Engineering Design Dimensions

Use this reference when exploring a software feature, architecture, implementation plan, or technical direction.

## Discovery

Clarify these before proposing a final direction:

- goal and user value
- target users or callers
- success criteria
- in-scope and out-of-scope behavior
- constraints such as stack, runtime, deployment, data, budget, compatibility, or deadlines
- existing system shape if a repository is available

## Architecture

Cover the minimum architecture needed for the decision:

- modules or subsystem boundaries
- data flow and state ownership
- external APIs, tools, files, queues, or services involved
- sync versus async behavior
- compatibility with existing patterns
- rollback or migration concerns when relevant

## Interface

When an interface is part of the design, define:

- inputs, outputs, and caller expectations
- required versus optional fields
- validation rules
- serialization format
- versioning or compatibility expectations
- examples only when they reduce ambiguity

## Safety And Reliability

Call out risks that affect implementation quality:

- permissions and least privilege
- data exposure, secrets, PII, or unsafe actions
- idempotency and retry behavior
- timeout and cancellation behavior
- error categories and user-facing failure messages
- observability fields needed for debugging

## Implementation Readiness

A plan is ready to implement when it states:

- the chosen approach
- the affected subsystems or likely files
- key data and control flow
- edge cases and failure modes
- test scenarios and acceptance criteria
- assumptions that should not be silently changed

