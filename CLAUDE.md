### 🔄 Project Awareness & Context
- **NEVER HARDCODE A VALUE** when the same value can be written into a configuration file and read into data instead. Prompt the user if you **ever** create a hard-coded value.
- **Always read 'NFL-MOCK-DRAFT-CONTEXT-ENGINEERING-PROMPT.md** at the start of a new conversation to understand the project's architecture, goals, style, and constraints.
- **Check `TASK.md`** before starting a new task. If the task isn't listed, add it with a brief description and today's date.
- **Use consistent naming conventions, file structure, and architecture patterns** as described in `PLANNING.md`.
- **Use venv_linux** (the virtual environment) whenever executing Python commands, including for unit tests.

### 🌐 Port Management - CRITICAL
- **ALWAYS run this web application on port 8988 ONLY.** Never change the port without explicit user permission.
- **If you need to run another service on a different port, ASK the user first.**
- **The default server port is 8988** - maintain this consistency across all sessions.
- **📋 MEMOIZATION RULE**: Every new directory MUST have a CLAUDE.md file that includes the port 8988 requirement.

### 🧱 Code Structure & Modularity
- **Never create a file longer than 500 lines of code.** If a file approaches this limit, refactor by splitting it into modules or helper files.
- **Organize code into clearly separated modules**, grouped by feature or responsibility.
  For agents this looks like:
    - `agent.py` - Main agent definition and execution logic 
    - `tools.py` - Tool functions used by the agent 
    - `prompts.py` - System prompts
- **Use clear, consistent imports** (prefer relative imports within packages).
- **Use clear, consistent imports** (prefer relative imports within packages).
- **Use python_dotenv and load_env()** for environment variables.

### 🧪 Testing & Reliability
- **Always create Pytest unit tests for new features** (functions, classes, routes, etc).
- **After updating any logic**, check whether existing unit tests need to be updated. If so, do it.
- **Tests should live in a `/tests` folder** mirroring the main app structure.
  - Include at least:
    - 1 test for expected use
    - 1 edge case
    - 1 failure case

### ✅ Task Completion
- **Mark completed tasks in `TASK.md`** immediately after finishing them.
- Add new sub-tasks or TODOs discovered during development to `TASK.md` under a “Discovered During Work” section.

### 📎 Style & Conventions
- **Use Python** as a secondary language.
- **Follow PEP8**, use type hints, and format with `black`.
- **Use `pydantic` for data validation**.
- Write **docstrings for every function** using the Google style:
  ```python
  def example():
      """
      Brief summary.

      Args:
          param1 (type): Description.

      Returns:
          type: Description.
      """
  ```

### 📚 Documentation & Explainability
- **Update `README.md`** when new features are added, dependencies change, or setup steps are modified.
- **Comment non-obvious code** and ensure everything is understandable to a mid-level developer.
- When writing complex logic, **add an inline `# Reason:` comment** explaining the why, not just the what.

### 🧠 AI Behavior Rules
- **Never assume missing context. Ask questions if uncertain.**
- **Never hallucinate libraries or functions** – only use known, verified Python packages.
- **Always confirm file paths and module names** exist before referencing them in code or tests.
- **Never delete or overwrite existing code** unless explicitly instructed to or if part of a task from `TASK.md`.

### 📦 Package Management - CRITICAL
- **ALWAYS use `uv` instead of `pip`** for Python package management
- Commands: `uv add <package>`, `uv run <script>`, `uv sync`
- uv is faster, more reliable, and provides better dependency resolution
- Use `uv run server.py` instead of `python3 server.py`

### 📝 Memoization Instructions
- **Memoize any input given in MEMOIZE.md file.**
- **This project focuses on agent-native RAG features to help users with document analysis and knowledge synthesis.**
