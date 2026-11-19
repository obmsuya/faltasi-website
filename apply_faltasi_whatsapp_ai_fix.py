from pathlib import Path
import py_compile
import shutil
import sys

ROOT = Path.cwd()

CHANGES = [
    (
        ROOT / "whatsapp" / "views.py",
        '''            ai_reply = get_ai_product_reply(
                text,
                organization,
                state,
                incoming_message.id if incoming_message else None,
            )

            if ai_reply:
                reply = ai_reply
                product_reply = None
            else:
                general_ai_reply = None

                # Reuse the earlier interpretation. Only call the
                # backward-compatible helper if interpretation was
                # not attempted earlier in this webhook path.
                if not general_ai_attempted:
                    general_ai_reply = get_ai_general_reply(
                        text,
                        organization,
                        state,
                        incoming_message.id if incoming_message else None,
                    )

                if general_ai_reply:
                    reply = general_ai_reply
                    product_reply = None
                else:
                    # First preserve the existing literal catalogue search.
                    product_reply = search_whatsapp_products(
                        text,
                        organization,
                        state,
                    )

                    if product_reply:
                        reply = product_reply
                    else:
                        # AI discovery is only a fallback when literal
                        # catalogue search finds no matching products.
                        discovery = get_ai_product_discovery_reply(
                            text,
                            organization,
                            state,
                            incoming_message.id if incoming_message else None,
                        )

                        if discovery:
                            reply = discovery["reply"]
                            product_reply = discovery["product_reply"]
                        else:
                            reply = (
                                "Samahani, sijapata taarifa inayotosha kujibu "
                                "swali lako. Tafadhali fafanua kidogo au wasiliana "
                                "na timu yetu kwa msaada zaidi."
                            )
''',
        '''            # The earlier general interpretation owns the route decision.
            # Do not let this fallback reinterpret a company/service question
            # as a product search.
            is_product_enquiry = (
                general_ai_attempted
                and isinstance(general_ai_result, dict)
                and general_ai_result.get("intent") == "product_enquiry"
            )

            if general_ai_attempted and not is_product_enquiry:
                product_reply = None
                if not reply:
                    reply = (
                        "Samahani, sijapata taarifa inayotosha kujibu "
                        "swali lako. Tafadhali fafanua kidogo au wasiliana "
                        "na timu yetu kwa msaada zaidi."
                    )
            else:
                # Only product enquiries (or paths where general
                # interpretation was not applicable) reach catalogue search.
                product_reply = search_whatsapp_products(
                    text,
                    organization,
                    state,
                )

                if product_reply:
                    reply = product_reply
                else:
                    discovery = get_ai_product_discovery_reply(
                        text,
                        organization,
                        state,
                        incoming_message.id if incoming_message else None,
                    )

                    if discovery:
                        reply = discovery["reply"]
                        product_reply = discovery["product_reply"]
                    else:
                        reply = (
                            "Samahani, sijapata taarifa inayotosha kujibu "
                            "swali lako. Tafadhali fafanua kidogo au wasiliana "
                            "na timu yetu kwa msaada zaidi."
                        )
''',
    ),
    (
        ROOT / "product_knowledge" / "search.py",
        '''def search_document_chunks(
    organization,
    query,
    limit=DEFAULT_LIMIT,
    *,
    can_access_admin_only=False,
):''',
        '''def search_document_chunks(
    organization,
    query,
    limit=DEFAULT_LIMIT,
    *,
    can_access_admin_only=False,
    customer_facing=False,
):''',
    ),
    (
        ROOT / "product_knowledge" / "search.py",
        '''    if not can_access_admin_only:
        queryset = queryset.filter(
            document__access_level=ProductKnowledgeDocument.AccessLevel.EMPLOYEE
        )

    queryset = queryset.select_related("document")''',
        '''    if not can_access_admin_only:
        queryset = queryset.filter(
            document__access_level=ProductKnowledgeDocument.AccessLevel.EMPLOYEE
        )

    # WhatsApp customers may only receive documents explicitly classified
    # as FAQs. Other Employee Access documents remain internal to AI STAFF.
    if customer_facing:
        queryset = queryset.filter(
            document__document_type=ProductKnowledgeDocument.DocumentType.FAQ
        )

    queryset = queryset.select_related("document")''',
    ),
    (
        ROOT / "product_knowledge" / "search.py",
        '''def retrieve_knowledge(
    organization,
    query,
    product_limit=5,
    document_limit=5,
    category_limit=5,
    *,
    can_access_admin_only=False,
):''',
        '''def retrieve_knowledge(
    organization,
    query,
    product_limit=5,
    document_limit=5,
    category_limit=5,
    *,
    can_access_admin_only=False,
    customer_facing=False,
):''',
    ),
    (
        ROOT / "product_knowledge" / "search.py",
        '''                limit=document_limit,
                can_access_admin_only=can_access_admin_only,
            )''',
        '''                limit=document_limit,
                can_access_admin_only=can_access_admin_only,
                customer_facing=customer_facing,
            )''',
    ),
    (
        ROOT / "product_knowledge" / "context.py",
        '''        category_limit=category_limit,
        can_access_admin_only=can_access_admin_only,
    )''',
        '''        category_limit=category_limit,
        can_access_admin_only=can_access_admin_only,
        customer_facing=customer_facing,
    )''',
    ),
]

def main():
    grouped = {}
    for path, old, new in CHANGES:
        if path not in grouped:
            if not path.is_file():
                raise SystemExit(f"Missing expected source file: {path}")
            grouped[path] = path.read_text(encoding="utf-8")
        if old not in grouped[path]:
            raise SystemExit(
                f"Expected code block was not found in {path}. "
                "No files have been changed. Check the current version first."
            )
        grouped[path] = grouped[path].replace(old, new, 1)

    # Back up every affected file before changing any of them.
    backups = []
    for path, updated in grouped.items():
        backup = path.with_name(path.name + ".before_whatsapp_ai_fix.bak")
        if backup.exists():
            raise SystemExit(
                f"Backup already exists: {backup}. "
                "Move it aside before applying this patch again."
            )
        backups.append((path, backup, updated))

    for path, backup, updated in backups:
        shutil.copy2(path, backup)
        path.write_text(updated, encoding="utf-8", newline="")

    try:
        for path, _, _ in backups:
            py_compile.compile(str(path), doraise=True)
    except Exception:
        for path, backup, _ in backups:
            shutil.copy2(backup, path)
        raise

    print("Applied the WhatsApp AI routing and FAQ retrieval changes.")
    print("Python syntax checks passed for all changed files.")
    print("Backups created:")
    for _, backup, _ in backups:
        print(f"  {backup}")

if __name__ == "__main__":
    main()
