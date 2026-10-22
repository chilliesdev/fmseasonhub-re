---
name: e2e-qa-tester
description: Performs end-to-end testing based on user descriptions, PRDs, Jira tickets, or specified requirements sources by simulating user behavior. Use this skill when you need a comprehensive QA audit, regression testing, or verification of features against requirements without modifying the code.
---

# E2E QA Tester

This skill enables a systematic, user-centric testing workflow. It focuses on identifying discrepancies between the current implementation and requirements provided via user instructions, PRD files, Jira tickets, or other specified sources.

## Core Principles

- **End-User Perspective:** Always simulate usage from the perspective of an end user using browser automation for UI or `curl` for APIs/services.
- **Zero-Fix Policy:** Do NOT attempt to fix any issues found during the testing phase. Your sole responsibility is to document them.
- **Evidence-Based:** Every failure or bug reported must include logs, error messages, or clear steps to reproduce.
- **Artifact Management:** Always delete all test artifacts (temporary files, test databases, logs created during testing) immediately after the test run is complete and the report is generated.

## Workflow

### 1. Requirements Gathering & Analysis
- **Identify Source:** Gather requirements from user description, PRD (e.g., `PRD.md`), Jira tickets, or explicitly specified files/documents.
- **Prompt If Missing:** If no requirement source is specified or found, ask the user to provide requirements or specify the source before proceeding.
- **Extract Flows:** List key features and expected user flows to verify.

### 2. Environment Setup & Prerequisite Verification
- Verify required testing tools (`curl` or browser tools/Chrome DevTools) are accessible.
- Verify project dependencies and build steps (`npm run build`, `make`, etc.).
- **Prerequisite / Dependency Failure:** If browser tools, `curl`, build scripts, or core dependencies fail or are unavailable, **stop execution immediately**. Document the exact missing/failed dependency as a Critical blocker in `QA_REPORT.md` and terminate testing early.

### 3. Execution & Simulation
For each requirement/user flow:
- **Simulate:** Run the actual software as a user would.
  - **Web / Frontend UI:** Use browser tools / Chrome DevTools to automate and test user interactions.
  - **APIs / Backends:** Use `curl` (or curl scripts) to send HTTP requests and verify responses.
- **Observe:** Check the output against the expected behavior defined in the requirements source.
- **Verify:** Look for edge cases, error handling, and performance issues.

### 4. Reporting
Generate a detailed report in `QA_REPORT.md` following the template in `references/QA_REPORT_TEMPLATE.md`.

### 5. Cleanup
Immediately after generating the `QA_REPORT.md`, identify and delete all temporary files, logs, test directories, or other artifacts created during the simulation phase to leave the workspace in its original state.

## Guidelines for QA_REPORT.md

- **Severity Levels:**
    - **Critical:** Crashes, data loss, or core functionality completely broken.
    - **Major:** Significant feature not working as expected, but workarounds might exist.
    - **Minor:** UI glitches, confusing messages, or non-critical feature issues.
    - **Trivial:** Typographical errors, minor styling issues.
- **Reproducibility:** If an issue is intermittent, note it clearly.

## Resources

- **references/QA_REPORT_TEMPLATE.md**: Use this template for the final report to ensure consistency and completeness.
