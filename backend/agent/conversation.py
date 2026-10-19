"""Bounded conversational replies; presentation hints never authorize domain tools."""

from backend.agent.classifier import IntentClassification
from backend.agent.state import ConversationState

REPLIES = {
    "GREETING": (
        "Hi! I’m Rantau. I can help you plan a tuition payment, track a transfer, "
        "or work through a payment problem.\n\nWhat would you like help with?"
    ),
    "HELP": (
        "Here’s what I can help with:\n\n"
        "- **Tuition:** review what’s due, compare routes and prepare a payment.\n"
        "- **Tracking:** check a transfer and whether the university credited it.\n"
        "- **Recovery:** investigate delayed posting, a missing reference or a shortfall.\n"
        "- **Message checks:** review suspicious payment instructions.\n"
        "- **Payment rules:** explain the current requirements.\n\n"
        "For example, say “Help me pay my tuition” or “Track my payment.”"
    ),
    "THANKS": "You’re welcome. If you need another payment check, I’m here to help.",
    "UNSUPPORTED_WEATHER": (
        "I can’t check the weather here. For a forecast, use a weather service.\n\n"
        "I can help with tuition, transfers or a payment that needs attention."
    ),
    "UNSUPPORTED_TRAVEL": (
        "I can’t book travel or plan an itinerary here.\n\n"
        "If your question is about paying tuition or checking a transfer, I can help with that."
    ),
    "UNSUPPORTED_ACADEMIC": (
        "I can’t write assignments or provide academic tutoring here.\n\n"
        "I can help with the payment side of university life: tuition, transfer tracking "
        "and payment problems."
    ),
    "UNSUPPORTED_FINANCIAL_ACTION": (
        "I can help with supported tuition payments, but I can’t provide loans or investments, "
        "add a new recipient, grant approval or remove a security hold.\n\n"
        "Tell me whether you want to review tuition, track an existing payment "
        "or investigate a problem."
    ),
    "UNSUPPORTED_GENERAL": (
        "That’s outside what I can help with here. My focus is tuition and payment support.\n\n"
        "I can review what you owe, compare payment routes, track a transfer or check "
        "suspicious payment instructions."
    ),
    "CLARIFY": (
        "I’m not sure which payment task you mean.\n\n"
        "Are you trying to **pay tuition**, **check an existing payment**, "
        "or **resolve a payment problem**?"
    ),
}


def conversational_reply(
    classification: IntentClassification, conversation: ConversationState | None = None
) -> str:
    if classification.reply_kind in {None, "CLARIFY"} and conversation is not None:
        questions = {
            "FUNDING": (
                "Which funding account would you like to use—your own account or another owner’s?"
            ),
            "AMOUNT": "What amount would you like to pay in CNY? You can also say `full balance`.",
            "QUOTE": "Which advertised route number would you like to use?",
            "OBLIGATION": "Which of the listed tuition bills would you like to review?",
        }
        if conversation.tuition.awaiting in questions:
            return questions[conversation.tuition.awaiting]
    return REPLIES[classification.reply_kind or "CLARIFY"]
