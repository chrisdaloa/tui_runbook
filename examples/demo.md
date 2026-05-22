# Demo Runbook

A sample runbook for testing the MVP locally.

## Print welcome message

Verify that text output works correctly.

```bash
echo "=== Runbook started ==="
echo "Date: $(date)"
echo "User: $(whoami)"
echo "Directory: $(pwd)"
```

## Greet the user

<!-- runbook:rollback: echo "Operation cancelled for ${NAME}" -->

Uses the `${NAME}` variable to personalise the message.

```bash
echo "Hello, ${NAME}!"
echo "Welcome to the interactive runbook."
```

## Manual confirmation

<!-- runbook:manual -->

Visually verify that the previous steps produced the expected output,
then press `r` to confirm and continue.

```bash
echo "confirmation received"
```

## Multi-step processing

<!-- runbook:rollback: echo "Rollback processing: restoring initial state" -->

Simulates an operation that takes a few seconds.

```bash
echo "Phase 1/3: preparation..."
sleep 1
echo "Phase 2/3: processing..."
sleep 1
echo "Phase 3/3: completion..."
echo "Done."
```

## Intentionally failing step

This step exits with code 1 to demonstrate error handling.

```bash
echo "This command is about to fail..."
echo "Simulated error" >&2
exit 1
```
