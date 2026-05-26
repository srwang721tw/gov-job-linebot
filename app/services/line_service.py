from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from app.services.query_service import handle_user_query
from app.utils.config import LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET
from app.utils.logger import logger

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event: MessageEvent) -> None:
    user_text = event.message.text
    logger.info(f"LINE message received: {user_text[:80]}")

    reply_text = handle_user_query(user_text)

    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)],
            )
        )
