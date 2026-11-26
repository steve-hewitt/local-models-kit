# hello-agent: the 5-minute end-to-end proof

Goal: prove the whole stack (OpenCode agent, tool calls, file edit, model) on a task too small to hide behind.

## Steps

1. From this folder, launch either path:
   - Baseline: `../../scripts/launch-direct.ps1` (or `.sh`), with this folder as the project folder
   - Full stack: `../../scripts/launch-headroom.ps1` (or `.sh`)
2. Give OpenCode this prompt, verbatim:

   > The tests in test_calc.py are failing. Find the bug in calc.py, fix only what is wrong, and run the tests to confirm they pass. Do not change the tests.

3. Expected agent behavior: read both files, edit `mul` in `calc.py` to use `*` instead of `+`, run the tests, report green.

Timing note: the first turn is the slowest thing in this kit. It pays the model load, and Flint thinks before it answers (hundreds of reasoning tokens even on small prompts). On a GPU-resident native Windows run expect a pause; CPU-only (for example Ollama inside WSL2 on AMD, where ROCm is not exposed) the first hands-on run took 56 seconds to 1m40s per turn. Slow is expected there; silent truncation is not. If the agent seems to lose the task instead, check `ollama ps`: CONTEXT should read 131072, and you should be on a `*-opencode` model, not a base tag at 4096.
4. Verify yourself afterwards, without the agent:

   ```
   python test_calc.py
   # expected: all tests passed
   ```

## Pass / fail

- **Pass:** tests green, diff touches only the one buggy line in `calc.py`.
- **Fail, instructive:** agent edits the test file (it was told not to), rewrites the whole module unprompted, or claims success without running anything. Note which happened and record it in `docs/reference/VALIDATION.md` on the target-hardware run. Small-model failure modes are data, not embarrassment.

## Then

Run the same task through the other launch path. Same result via both paths is the actual proof that Headroom is transparent for real work, and the Headroom dashboard number from the wrapped run is your first real compression measurement.
