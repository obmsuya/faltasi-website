import requests
import json

url = "http://127.0.0.1:8000/whatsapp/webhook/"

payload = {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "id": "1385206683126881",
            "changes": [
                {
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "display_phone_number": "255745769908",
                            "phone_number_id": "1340632705795392"
                        },
                        "contacts": [
                            {
                                "profile": {
                                    "name": "Automatic Assignment Test Customer"
                                },
                                "wa_id": "255764819996"
                            }
                        ],
                        "messages": [
                            {
                                "from": "255764819996",
                                "id": "TEST-INCOMING-001",
                                "timestamp": "1758830000",
                                "type": "text",
                                "text": {
                                    "body": "Hello, I need help"
                                }
                            }
                        ]
                    }
                }
            ]
        }
    ]
}

response = requests.post(
    url,
    json=payload,
    timeout=30
)

print("STATUS:", response.status_code)
print("RESPONSE:", response.text)