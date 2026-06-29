import os
from dotenv import load_dotenv
from google import genai

# 1. Connect the code to your hidden API key file
load_dotenv()

# 2. Start the Gemini Client
client = genai.Client()

print("==================================================")
print("🤖 Welcome to your first interactive AI Terminal! 🤖")
print("==================================================")
print("Type 'exit' or 'quit' at any time to stop.\n")

# 3. Create a loop so they can test multiple prompts
while True:
    # Accept custom user input from the terminal
    user_prompt = input("✍️ Enter your prompt for Gemini: ")
    
    # Check if the student wants to close the program
    if user_prompt.lower() in ['exit', 'quit']:
        print("\nGoodbye! Happy coding! 🚀")
        break
        
    # Skip empty inputs
    if not user_prompt.strip():
        print("Please type something before pressing Enter.\n")
        continue

    print("\n⏳ Sending your prompt to Google's servers...")

    # 4. THE API CALL: This sends the prompt to the cloud and waits for the answer
    response = client.models.generate_content(
        model="gemini-2.5-flash",  # You can change this to other Gemini models if you want
        contents=user_prompt,
    )

    # 5. THE RESPONSE: Display what the AI sent back
    print("\n✨ Gemini's Answer:")
    print(response.text)
    print("==================================================\n")