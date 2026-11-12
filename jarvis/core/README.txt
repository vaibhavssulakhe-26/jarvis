Starts Jarvis and keeps its settings and shared state.
main.py decides what happens to each command you give it.
config.py reads the settings and keys from the .env file.
errors.py holds ToolError, the one error type whose message is safe to speak.
jsonfile.py reads and writes the small JSON files under data/.
state.py lets the window, the background service and Jarvis share a few flags.
