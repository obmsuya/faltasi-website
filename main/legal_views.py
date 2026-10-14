
from django.http import HttpResponse


def terms_of_service(request):
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Terms of Service | Faltasi Innovations Limited</title>
    </head>
    <body style="font-family: Arial, sans-serif; max-width: 850px;
                 margin: 40px auto; padding: 20px; line-height: 1.7;">
        <h1>Terms of Service</h1>
        <p><strong>Faltasi Innovations Limited</strong></p>
        <p>Last updated: 14 October 2026</p>

        <h2>1. About Our Services</h2>
        <p>Faltasi Innovations Limited provides technology solutions,
        software and systems development, business tools, and services
        that help organizations manage their operations and communicate
        with customers, including through WhatsApp integrations.</p>

        <h2>2. Acceptable Use</h2>
        <p>Users must provide accurate information, protect their login
        credentials, comply with applicable laws, and use our services
        only for lawful business purposes. Users must not send unlawful,
        misleading, fraudulent, or unauthorized communications.</p>

        <h2>3. WhatsApp Services</h2>
        <p>WhatsApp features depend on the permissions and business
        assets authorized by the relevant organization, as well as
        applicable Meta and WhatsApp policies. Users are responsible
        for having the necessary rights and permissions to contact
        their recipients.</p>

        <h2>4. Accounts and Security</h2>
        <p>Users are responsible for protecting their account details
        and notifying us of suspected unauthorized access. We may
        restrict access when necessary to protect users, our platform,
        or comply with the law.</p>

        <h2>5. Availability and Changes</h2>
        <p>We aim to provide reliable services but cannot guarantee
        uninterrupted availability. Features and services may change
        as the platform develops.</p>

        <h2>6. Privacy and Data</h2>
        <p>Our handling of personal information is described in our
        <a href="/privacy-policy/">Privacy Policy</a>. Requests concerning
        personal data can be made using our
        <a href="/data-deletion/">Data Deletion Instructions</a>.</p>

        <h2>7. Contact</h2>
        <p>Faltasi Innovations Limited<br>
        Website: <a href="https://www.faltasi.com/">www.faltasi.com</a><br>
        Phone: 0764819996<br>
        Email: obmsuya@gmail.com</p>
    </body>
    </html>
    """
    return HttpResponse(html)


def data_deletion(request):
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Data Deletion Instructions | Faltasi Innovations Limited</title>
    </head>
    <body style="font-family: Arial, sans-serif; max-width: 850px;
                 margin: 40px auto; padding: 20px; line-height: 1.7;">
        <h1>Data Deletion Instructions</h1>
        <p><strong>Faltasi Innovations Limited</strong></p>
        <p>Last updated: 14 October 2026</p>

        <h2>How to Request Deletion</h2>
        <p>If you want Faltasi Innovations Limited to delete personal
        information associated with your use of our platform or WhatsApp
        integration, contact us using the details below.</p>

        <p>Email: <a href="mailto:obmsuya@gmail.com">obmsuya@gmail.com</a><br>
        Phone: 0764819996</p>

        <h2>Information to Include</h2>
        <p>Please provide your name, the phone number or email address
        associated with your interaction, and a description of the
        information you want deleted. Do not send passwords or access
        tokens.</p>

        <h2>What Happens Next?</h2>
        <p>We will review your request, verify your identity where
        reasonably necessary, and explain or carry out the appropriate
        deletion steps. We may retain certain information when required
        by law or for legitimate security and recordkeeping purposes.
        Where information must be retained, we will handle it according
        to applicable requirements.</p>

        <h2>Meta and WhatsApp Data</h2>
        <p>If your request concerns information handled through Facebook,
        Meta, or WhatsApp, please identify that in your request so we
        can assess which information is held by Faltasi and what action
        is available.</p>

        <h2>Contact</h2>
        <p>Faltasi Innovations Limited<br>
        Website: <a href="https://www.faltasi.com/">www.faltasi.com</a><br>
        Phone: 0764819996<br>
        Email: obmsuya@gmail.com</p>

        <p><a href="/privacy-policy/">Privacy Policy</a> |
        <a href="/terms/">Terms of Service</a></p>
    </body>
    </html>
    """
 



def terms_of_service(request):
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Terms of Service | Faltasi Innovations Limited</title>
    </head>
    <body style="font-family:Arial,sans-serif;max-width:850px;margin:40px auto;padding:20px;line-height:1.7">
        <h1>Terms of Service</h1>
        <p><strong>Faltasi Innovations Limited</strong></p>
        <p>Last updated: 14 October 2026</p>

        <h2>1. About Our Services</h2>
        <p>Faltasi Innovations Limited provides technology solutions,
        software and systems development, business tools, and services
        that help organizations manage operations and communicate with
        customers, including through WhatsApp integrations.</p>

        <h2>2. Acceptable Use</h2>
        <p>Users must provide accurate information, protect their
        credentials, comply with applicable laws, and use our services
        for lawful purposes. Unauthorized or unlawful communications
        are prohibited.</p>

        <h2>3. WhatsApp Services</h2>
        <p>WhatsApp features depend on the permissions and business
        assets authorized by the relevant organization and applicable
        Meta and WhatsApp policies.</p>

        <h2>4. Accounts and Security</h2>
        <p>Users are responsible for protecting their account details
        and notifying us of suspected unauthorized access.</p>

        <h2>5. Availability and Changes</h2>
        <p>We aim to provide reliable services but cannot guarantee
        uninterrupted availability. Features may change as the platform
        develops.</p>

        <h2>6. Privacy and Data</h2>
        <p>Read our <a href="/privacy-policy/">Privacy Policy</a> and
        <a href="/data-deletion/">Data Deletion Instructions</a>.</p>

        <h2>7. Contact</h2>
        <p>Faltasi Innovations Limited<br>
        Website: <a href="https://www.faltasi.com/">www.faltasi.com</a><br>
        Phone: 0764819996<br>
        Email: obmsuya@gmail.com</p>
    </body>
    </html>
    """
    return HttpResponse(html)


def data_deletion(request):
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Data Deletion Instructions | Faltasi Innovations Limited</title>
    </head>
    <body style="font-family:Arial,sans-serif;max-width:850px;margin:40px auto;padding:20px;line-height:1.7">
        <h1>Data Deletion Instructions</h1>
        <p><strong>Faltasi Innovations Limited</strong></p>
        <p>Last updated: 14 October 2026</p>

        <h2>How to Request Deletion</h2>
        <p>To request deletion of personal information associated with
        your use of our platform or WhatsApp integration, contact us
        using the details below.</p>

        <h2>Information to Include</h2>
        <p>Provide your name, the phone number or email address
        associated with your interaction, and a description of the
        information you want deleted. Do not send passwords or access tokens.</p>

        <h2>What Happens Next?</h2>
        <p>We will review your request and verify your identity where
        reasonably necessary. We will assess the request and explain or
        carry out appropriate deletion steps. Some information may need
        to be retained where required by law.</p>

        <h2>Contact</h2>
        <p>Faltasi Innovations Limited<br>
        Website: <a href="https://www.faltasi.com/">www.faltasi.com</a><br>
        Phone: 0764819996<br>
        Email: <a href="mailto:obmsuya@gmail.com">obmsuya@gmail.com</a></p>

        <p><a href="/terms/">Terms of Service</a> |
        <a href="/privacy-policy/">Privacy Policy</a></p>
    </body>
    </html>
    """
    return HttpResponse(html)
