from django.shortcuts import render

# Create your views here.
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
import json



@csrf_exempt
def webhook(request):
    print("========== WHATSAPP WEBHOOK ==========")
    print("METHOD:", request.method)
    print("PATH:", request.path)
    print("HEADERS:", dict(request.headers))

    if request.method == "GET":
        verify_token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge")

        print("VERIFY TOKEN:", verify_token)
        print("CHALLENGE:", challenge)

        if verify_token == settings.WHATSAPP_VERIFY_TOKEN:
            print("VERIFICATION SUCCESS")
            return HttpResponse(challenge)

        print("VERIFICATION FAILED")
        return HttpResponse("Invalid verify token", status=403)

    if request.method == "POST":
        print("========== POST RECEIVED ==========")
        print("BODY:", request.body.decode("utf-8", errors="replace"))

        try:
            data = json.loads(request.body)

            print("JSON:")
            print(json.dumps(data, indent=2))

            return JsonResponse({"status": "ok"})

        except json.JSONDecodeError as e:
            print("JSON ERROR:", e)
            return JsonResponse({"error": "Invalid JSON"}, status=400)

    return HttpResponse(status=405)