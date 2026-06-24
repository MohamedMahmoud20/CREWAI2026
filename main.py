import sys
from auth.login import login_user
from llm.ollama_client import local_llm
from config.settings import USERS_API_BASE, OLLAMA_BASE_URL, OLLAMA_MODEL


def test_login():
    print("\n--- Test Login ---")
    email = input("Enter email: ").strip()
    password = input("Enter password: ").strip()
    if not email or not password:
        print("Error: Email and password are required.")
        return

    print("Authenticating...")
    token, company_id, err = login_user(email, password)
    if err:
        print(f"Login failed: {err}")
    else:
        print("Login successful!")
        print(f"Token: {token}")
        print(f"Company ID: {company_id}")


def test_ollama():
    print("\n--- Test Ollama Connection ---")
    print(f"Checking connection to Ollama at {OLLAMA_BASE_URL}...")
    if not local_llm.verify_connection():
        print("Error: Could not connect to Ollama server.")
        return
    print("Ollama server is active.")

    prompt = input("Enter a prompt for the LLM: ").strip()
    if not prompt:
        prompt = "Say hello!"
        print(f"Using default prompt: {prompt}")

    print("Generating response...")
    try:
        response = local_llm.generate(prompt)
        print("\n--- LLM Response ---")
        print(response)
    except Exception as e:
        print(f"Failed to generate response: {e}")


def main():
    print("====================================================")
    print("Project: Minimal Authentication and Ollama Client")
    print(f"API Base: {USERS_API_BASE}")
    print(f"Ollama Base: {OLLAMA_BASE_URL}")
    print(f"Ollama Model: {OLLAMA_MODEL}")
    print("====================================================")

    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == "login":
            test_login()
        elif cmd == "ollama":
            test_ollama()
        else:
            print(f"Unknown command: {cmd}")
            print("Available commands: login, ollama")
        return

    while True:
        print("\nOptions:")
        print("1. Test User Login")
        print("2. Test Ollama Generation")
        print("3. Exit")
        choice = input("Select an option (1-3): ").strip()
        if choice == "1":
            test_login()
        elif choice == "2":
            test_ollama()
        elif choice == "3":
            print("Exiting...")
            break
        else:
            print("Invalid choice, please select 1, 2, or 3.")


if __name__ == "__main__":
    main()
