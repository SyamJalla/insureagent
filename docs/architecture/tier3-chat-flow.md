
flowchart TD
    A[User sends a chat message with Tier 3 selected] --> B{Is LAYA_API_KEY configured?}

    B -- No --> F[Skip Laya classification]
    B -- Yes --> C[Send message to Laya for classification]

    C --> D{Recognized domain and confidence at least 0.85?}
    D -- Yes --> E[Route to billing, policy, or claims specialist]
    D -- No --> F

    E --> G[Specialist uses TIER3_WORKER_MODEL via Groq]
    F --> H[Supervisor decides how to handle the message]
    H --> I[Use TIER2_SPECIALIST_MODEL for fallback execution]

    G --> J[Tools fetch authorized data]
    I --> J
    J --> K[Compose and return the final answer]
