
import csv
import tempfile
from pathlib import Path

from django.core.files.base import ContentFile
from django.test import SimpleTestCase, TestCase, override_settings

from organizations.models import Organization

from .extractors import (
    DocumentExtractionError,
    extract_document_text,
)
from .models import (
    ProductKnowledgeDocument,
    ProductKnowledgeChunk,
)
from .processing import (
    process_document,
    split_text_into_chunks,
)

from .search import (
    search_organization_products,
    search_document_chunks,
    get_request_categories,
    retrieve_knowledge,
)
from .context import (
    MAX_CONTEXT_CHARS,
    build_knowledge_context,
)

from django.contrib.auth.models import User
from django.urls import reverse
from organizations.models import OrganizationMember

from products.models import Product
from business_requests.models import (
    Department,
    RequestCategory,
    RequestField,
)








# ---------------------------------------------------------
# DOCUMENT EXTRACTION TESTS
# ---------------------------------------------------------

class DocumentExtractionTests(SimpleTestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.directory = Path(self.temp_dir.name)

    def test_extract_txt(self):
        path = self.directory / "products.txt"
        path.write_text(
            "Product: Router\nPrice: 150000 TZS",
            encoding="utf-8",
        )

        result = extract_document_text(path)

        self.assertIn("Router", result["text"])
        self.assertIn("150000 TZS", result["text"])
        self.assertEqual(result["file_extension"], "txt")
        self.assertIsNone(result["page_count"])

    def test_extract_csv(self):
        path = self.directory / "products.csv"

        with path.open(
            "w",
            encoding="utf-8",
            newline="",
        ) as file:
            writer = csv.writer(file)
            writer.writerow(["Product", "Price"])
            writer.writerow(["Network Switch", "250000"])

        result = extract_document_text(path)

        self.assertIn("Network Switch", result["text"])
        self.assertIn("250000", result["text"])
        self.assertEqual(result["file_extension"], "csv")

    def test_reject_unsupported_extension(self):
        path = self.directory / "products.exe"
        path.write_text("not supported", encoding="utf-8")

        with self.assertRaises(DocumentExtractionError):
            extract_document_text(path)

    def test_reject_empty_file(self):
        path = self.directory / "empty.txt"
        path.write_text("", encoding="utf-8")

        with self.assertRaises(DocumentExtractionError):
            extract_document_text(path)

    def test_reject_missing_file(self):
        path = self.directory / "missing.txt"

        with self.assertRaises(DocumentExtractionError):
            extract_document_text(path)


# ---------------------------------------------------------
# DOCUMENT PROCESSING TESTS
# ---------------------------------------------------------

class DocumentProcessingTests(TestCase):

    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.media_dir.cleanup)

        # Isolate uploaded test files from the project's actual media.
        self.settings_override = override_settings(
            MEDIA_ROOT=self.media_dir.name,
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)

        self.organization = Organization.objects.create(
            name="Knowledge Test Organization",
            organization_type="business",
            status="active",
        )

    def create_document(self, content, filename="products.txt"):
        document = ProductKnowledgeDocument(
            organization=self.organization,
            title="Test Product Knowledge",
        )

        document.file.save(
            filename,
            ContentFile(
                content.encode("utf-8")
                if isinstance(content, str)
                else content
            ),
            save=False,
        )

        document.save()

        # Clean up the stored file after each test.
        self.addCleanup(
            document.file.storage.delete,
            document.file.name,
        )

        return document

    def test_split_text_creates_chunks(self):
        text = ("Product information. " * 400).strip()

        chunks = split_text_into_chunks(text)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(chunk.strip() for chunk in chunks))
        self.assertTrue(all(len(chunk) <= 2500 for chunk in chunks))

    def test_split_empty_text_returns_no_chunks(self):
        self.assertEqual(split_text_into_chunks(""), [])
        self.assertEqual(split_text_into_chunks("   "), [])

    def test_process_document_saves_text_and_chunks(self):
        document = self.create_document(
            "Product: Network Router\nPrice: 150000 TZS"
        )

        processed = process_document(document.pk)
        processed.refresh_from_db()

        self.assertEqual(
            processed.status,
            ProductKnowledgeDocument.Status.READY,
        )
        self.assertIn("Network Router", processed.extracted_text)
        self.assertIn("150000 TZS", processed.extracted_text)
        self.assertEqual(processed.chunk_count, 1)

        chunks = ProductKnowledgeChunk.objects.filter(
            document=processed
        )

        self.assertEqual(chunks.count(), 1)
        self.assertEqual(
            chunks.first().organization_id,
            self.organization.pk,
        )
        self.assertEqual(
            processed.index_status,
            ProductKnowledgeDocument.IndexStatus.PENDING,
        )
        self.assertIsNotNone(processed.processing_completed_at)

    def test_processing_failure_marks_document_failed(self):
        document = self.create_document(
            b"This is not a valid PDF.",
            filename="invalid.pdf",
        )

        with self.assertRaises(DocumentExtractionError):
            process_document(document.pk)

        document.refresh_from_db()

        self.assertEqual(
            document.status,
            ProductKnowledgeDocument.Status.FAILED,
        )
        self.assertTrue(document.processing_error)
        self.assertIsNotNone(document.processing_completed_at)

    def test_failed_reprocessing_preserves_existing_chunks(self):
        document = self.create_document(
            "Original product details and price."
        )

        process_document(document.pk)

        original_chunks = list(
            ProductKnowledgeChunk.objects.filter(
                document=document
            ).values_list("chunk_index", "text")
        )

        # Replace the source file with invalid PDF content.
        document.file.save(
            "invalid.pdf",
            ContentFile(b"not a valid PDF"),
            save=True,
        )

        self.addCleanup(
            document.file.storage.delete,
            document.file.name,
        )

        with self.assertRaises(DocumentExtractionError):
            process_document(document.pk)

        remaining_chunks = list(
            ProductKnowledgeChunk.objects.filter(
                document=document
            ).values_list("chunk_index", "text")
        )

        self.assertEqual(remaining_chunks, original_chunks)

        document.refresh_from_db()
        self.assertEqual(
            document.status,
            ProductKnowledgeDocument.Status.FAILED,
        )


class KnowledgeSearchTests(TestCase):

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Search Test Organization",
            organization_type="business",
            status="active",
        )

        self.other_organization = Organization.objects.create(
            name="Other Search Organization",
            organization_type="business",
            status="active",
        )

    def test_search_products_returns_matching_product(self):
        product = Product.objects.create(
            organization=self.organization,
            name="Network Router",
            sku="RTR-100",
            brand="Faltasi",
            price="150000.00",
            currency="TZS",
            show_on_whatsapp=True,
            is_active=True,
        )

        results = search_organization_products(
            self.organization,
            "Network Router",
        )

        self.assertTrue(results)
        self.assertEqual(results[0]["id"], product.pk)
        self.assertEqual(results[0]["name"], "Network Router")
        self.assertEqual(results[0]["price"], "150000.00")

    def test_search_products_does_not_return_other_organization(self):
        Product.objects.create(
            organization=self.other_organization,
            name="Network Router",
            sku="OTHER-100",
            show_on_whatsapp=True,
            is_active=True,
        )

        results = search_organization_products(
            self.organization,
            "Network Router",
        )

        self.assertEqual(results, [])

    def test_search_products_excludes_inactive_and_hidden_products(self):
        Product.objects.create(
            organization=self.organization,
            name="Inactive Router",
            is_active=False,
            show_on_whatsapp=True,
        )

        Product.objects.create(
            organization=self.organization,
            name="Hidden Router",
            is_active=True,
            show_on_whatsapp=False,
        )

        results = search_organization_products(
            self.organization,
            "Router",
        )

        self.assertEqual(results, [])

    def test_empty_product_query_returns_no_results(self):
        Product.objects.create(
            organization=self.organization,
            name="Network Router",
            show_on_whatsapp=True,
            is_active=True,
        )

        self.assertEqual(
            search_organization_products(self.organization, ""),
            [],
        )


    def test_canonical_search_matches_product_name_brand_and_model(self):
        product = Product.objects.create(
            organization=self.organization,
            name="HP EliteBook 840 G8",
            sku="HP-840-G8",
            brand="HP",
            model="EliteBook 840 G8",
            price="850000.00",
            currency="TZS",
            show_on_whatsapp=True,
            is_active=True,
        )

        results = search_organization_products(
            self.organization,
            "HP EliteBook 840 G8",
        )

        self.assertTrue(results)
        self.assertEqual(results[0]["id"], product.pk)
        self.assertEqual(results[0]["name"], product.name)
        self.assertEqual(results[0]["sku"], product.sku)
        self.assertEqual(results[0]["brand"], product.brand)
        self.assertEqual(results[0]["model"], product.model)
        self.assertEqual(results[0]["price"], "850000.00")
        self.assertIn("image_url", results[0])
        self.assertIn("availability_display", results[0])
        self.assertNotIn("cost_price", results[0])

    def test_canonical_search_handles_swahili_product_query(self):
        product = Product.objects.create(
            organization=self.organization,
            name="HP Laptop",
            brand="HP",
            show_on_whatsapp=True,
            is_active=True,
        )

        results = search_organization_products(
            self.organization,
            "Nataka kununua HP Laptop",
        )

        self.assertTrue(results)
        self.assertEqual(results[0]["id"], product.pk)

    def test_canonical_search_excludes_other_organizations(self):
        Product.objects.create(
            organization=self.other_organization,
            name="Network Router",
            show_on_whatsapp=True,
            is_active=True,
        )

        results = search_organization_products(
            self.organization,
            "Network Router",
        )

        self.assertEqual(results, [])

    def test_canonical_search_excludes_inactive_deleted_and_hidden_products(self):
        from django.utils import timezone

        Product.objects.create(
            organization=self.organization,
            name="Inactive Router",
            is_active=False,
            show_on_whatsapp=True,
        )

        Product.objects.create(
            organization=self.organization,
            name="Deleted Router",
            is_active=True,
            show_on_whatsapp=True,
            deleted_at=timezone.now(),
        )

        Product.objects.create(
            organization=self.organization,
            name="Hidden Router",
            is_active=True,
            show_on_whatsapp=False,
        )

        results = search_organization_products(
            self.organization,
            "Router",
        )

        self.assertEqual(results, [])


    def test_document_search_returns_matching_chunk(self):
        document = ProductKnowledgeDocument.objects.create(
            organization=self.organization,
            title="Router Technical Manual",
            document_type=(
                ProductKnowledgeDocument.DocumentType.PRODUCT_MANUAL
            ),
            status=ProductKnowledgeDocument.Status.READY,
            index_status=(
                ProductKnowledgeDocument.IndexStatus.PENDING
            ),
            access_level=ProductKnowledgeDocument.AccessLevel.EMPLOYEE,
            is_active=True,
        )

        chunk = ProductKnowledgeChunk.objects.create(
            document=document,
            organization=self.organization,
            chunk_index=0,
            text="The network router supports dual-band WiFi.",
        )

        results = search_document_chunks(
            self.organization,
            "dual-band WiFi",
        )

        self.assertTrue(results)
        self.assertEqual(results[0]["chunk_id"], chunk.pk)
        self.assertEqual(
            results[0]["title"],
            "Router Technical Manual",
        )

    def test_document_search_excludes_other_organization(self):
        document = ProductKnowledgeDocument.objects.create(
            organization=self.other_organization,
            title="Private Router Manual",
            status=ProductKnowledgeDocument.Status.READY,
            index_status=(
                ProductKnowledgeDocument.IndexStatus.PENDING
            ),
            is_active=True,
        )

        ProductKnowledgeChunk.objects.create(
            document=document,
            organization=self.other_organization,
            chunk_index=0,
            text="Private network router configuration details.",
        )

        results = search_document_chunks(
            self.organization,
            "network router configuration",
        )

        self.assertEqual(results, [])

    def test_document_search_never_returns_another_organizations_profile(self):
        document = ProductKnowledgeDocument.objects.create(
            organization=self.organization,
            title="Organization Profile",
            status=ProductKnowledgeDocument.Status.READY,
            index_status=(
                ProductKnowledgeDocument.IndexStatus.PENDING
            ),
            is_active=True,
        )

        ProductKnowledgeChunk.objects.create(
            document=document,
            organization=self.organization,
            chunk_index=0,
            text="Confidential organization profile information.",
        )

        results = search_document_chunks(
            self.other_organization,
            "confidential organization profile information",
        )

        self.assertEqual(results, [])


    def test_document_search_excludes_archived_or_inactive_documents(self):
        document = ProductKnowledgeDocument.objects.create(
            organization=self.organization,
            title="Archived Router Manual",
            status=ProductKnowledgeDocument.Status.ARCHIVED,
            is_active=False,
        )

        ProductKnowledgeChunk.objects.create(
            document=document,
            organization=self.organization,
            chunk_index=0,
            text="Router installation and configuration.",
        )

        results = search_document_chunks(
            self.organization,
            "router installation",
        )

        self.assertEqual(results, [])

    def test_excel_configured_questions_are_returned_in_order(self):
        department = Department.objects.create(
            organization=self.organization,
            name="Technical Support",
            is_active=True,
        )

        category = RequestCategory.objects.create(
            organization=self.organization,
            department=department,
            name="Router Installation",
            description="Request router installation.",
            keywords="router, installation, setup",
            is_active=True,
        )

        # These represent questions configured through Excel.
        second_field = RequestField.objects.create(
            category=category,
            name="installation_location",
            question="Where should we install the router?",
            field_type="text",
            is_required=True,
            order=2,
            is_active=True,
        )

        first_field = RequestField.objects.create(
            category=category,
            name="router_quantity",
            question="How many routers do you need?",
            field_type="number",
            is_required=True,
            order=1,
            is_active=True,
        )

        results = get_request_categories(
            self.organization,
            "router installation",
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], category.pk)
        self.assertEqual(
            [question["name"] for question in results[0]["questions"]],
            [first_field.name, second_field.name],
        )
        self.assertEqual(
            results[0]["questions"][0]["question"],
            first_field.question,
        )
        self.assertTrue(results[0]["questions"][0]["required"])

    def test_excel_category_search_excludes_other_organization(self):
        department = Department.objects.create(
            organization=self.other_organization,
            name="Other Technical Support",
        )

        RequestCategory.objects.create(
            organization=self.other_organization,
            department=department,
            name="Router Installation",
            keywords="router, installation",
            is_active=True,
        )

        results = get_request_categories(
            self.organization,
            "router installation",
        )

        self.assertEqual(results, [])
    def test_retrieve_knowledge_returns_all_three_sources(self):
        Product.objects.create(
            organization=self.organization,
            name="Faltasi Network Router",
            sku="FAL-ROUTER-01",
            price="150000.00",
            currency="TZS",
            show_on_whatsapp=True,
            is_active=True,
        )

        document = ProductKnowledgeDocument.objects.create(
            organization=self.organization,
            title="Router Installation Manual",
            document_type=(
                ProductKnowledgeDocument.DocumentType.PRODUCT_MANUAL
            ),
            status=ProductKnowledgeDocument.Status.READY,
            index_status=(
                ProductKnowledgeDocument.IndexStatus.PENDING
            ),
            access_level=ProductKnowledgeDocument.AccessLevel.EMPLOYEE,
            is_active=True,
        )

        ProductKnowledgeChunk.objects.create(
            document=document,
            organization=self.organization,
            chunk_index=0,
            text="Faltasi Network Router supports dual-band WiFi.",
        )

        department = Department.objects.create(
            organization=self.organization,
            name="Technical Support",
        )

        RequestCategory.objects.create(
            organization=self.organization,
            department=department,
            name="Router Installation",
            keywords="router, installation",
            is_active=True,
        )

        results = retrieve_knowledge(
            self.organization,
            "router installation",
        )

        self.assertTrue(results["products"])
        self.assertTrue(results["documents"])
        self.assertTrue(results["request_categories"])

        self.assertEqual(
            results["products"][0]["source"],
            "product",
        )
        self.assertEqual(
            results["documents"][0]["source"],
            "document",
        )
        self.assertEqual(
            results["request_categories"][0]["source"],
            "excel_request_configuration",
        )
    
    def test_context_builder_excludes_other_organization_data(self):
        Product.objects.create(
            organization=self.other_organization,
            name="Confidential Router",
            description="Private product information.",
            show_on_whatsapp=True,
            is_active=True,
        )

        document = ProductKnowledgeDocument.objects.create(
            organization=self.other_organization,
            title="Confidential Router Manual",
            status=ProductKnowledgeDocument.Status.READY,
            index_status=(
                ProductKnowledgeDocument.IndexStatus.PENDING
            ),
            is_active=True,
        )

        ProductKnowledgeChunk.objects.create(
            document=document,
            organization=self.other_organization,
            chunk_index=0,
            text="Confidential router password and configuration.",
        )

        result = build_knowledge_context(
            organization=self.organization,
            query="router configuration",
        )

        self.assertNotIn(
            "Confidential Router",
            result["context_text"],
        )
        self.assertNotIn(
            "Confidential router password",
            result["context_text"],
        )
        self.assertEqual(result["retrieval"]["products"], [])
        self.assertEqual(result["retrieval"]["documents"], [])

    def test_context_builder_limits_query_and_context_size(self):
        oversized_query = "router " * (MAX_CONTEXT_CHARS * 3)

        result = build_knowledge_context(
            organization=self.organization,
            query=oversized_query,
        )

        self.assertLessEqual(
            len(result["query"]),
            MAX_CONTEXT_CHARS,
        )
        self.assertLessEqual(
            len(result["context_text"]),
            MAX_CONTEXT_CHARS,
        )
        self.assertIn(
            "Never disclose information belonging to another organization.",
            result["context_text"],
        )



from unittest.mock import Mock, patch

from django.test import TestCase

from .ai_service import (
    AIStaffConfigurationError,
    AIStaffUnavailableError,
    generate_answer,
)


class AIStaffServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from organizations.models import Organization

        cls.organization = Organization.objects.create(
            name="AI STAFF Test Organization",
        )

    def setUp(self):
        self.env_patcher = patch.dict(
            "os.environ",
            {
                "OPENAI_API_KEY": "test-key-not-real",
                "OPENAI_MODEL": "test-model",
            },
        )
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)

        self.knowledge_patcher = patch(
            "product_knowledge.ai_service.build_knowledge_context",
            return_value={
                "instructions": "Answer using the supplied context.",
                "context_text": "Test product costs 100 TZS.",
                "retrieval": {"products": [], "documents": []},
            },
        )
        self.mock_knowledge = self.knowledge_patcher.start()
        self.addCleanup(self.knowledge_patcher.stop)

        self.client = Mock()
        self.client.responses.create.return_value.output_text = (
            "The listed price is 100 TZS."
        )

    def test_successful_answer_uses_configured_model_and_context(self):
        result = generate_answer(
            self.organization,
            "What is the price?",
            client=self.client,
        )

        self.assertEqual(
            result["answer"],
            "The listed price is 100 TZS.",
        )
        self.assertEqual(result["model"], "test-model")
        self.assertEqual(result["sources"], {"products": [], "documents": []})

        self.client.responses.create.assert_called_once()
        call = self.client.responses.create.call_args.kwargs
        self.assertEqual(call["model"], "test-model")
        self.assertEqual(
            call["instructions"],
            "Answer using the supplied context.",
        )
        self.assertIn("Test product costs 100 TZS.", call["input"])

        self.mock_knowledge.assert_called_once_with(
            organization=self.organization,
            query="What is the price?",
            can_access_admin_only=False,
        )

    def test_missing_api_key_is_rejected(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
            with self.assertRaises(AIStaffConfigurationError):
                generate_answer(
                    self.organization,
                    "What is the price?",
                    client=self.client,
                )

        self.client.responses.create.assert_not_called()

    def test_missing_model_is_rejected(self):
        with patch.dict("os.environ", {"OPENAI_MODEL": ""}):
            with self.assertRaises(AIStaffConfigurationError):
                generate_answer(
                    self.organization,
                    "What is the price?",
                    client=self.client,
                )

        self.client.responses.create.assert_not_called()

    def test_empty_question_is_rejected(self):
        with self.assertRaises(ValueError):
            generate_answer(self.organization, "  ", client=self.client)

        self.client.responses.create.assert_not_called()

    def test_oversized_question_is_rejected(self):
        with self.assertRaises(ValueError):
            generate_answer(
                self.organization,
                "x" * 4001,
                client=self.client,
            )

        self.client.responses.create.assert_not_called()

    def test_empty_ai_response_is_rejected(self):
        self.client.responses.create.return_value.output_text = "  "

        with self.assertRaises(AIStaffUnavailableError):
            generate_answer(
                self.organization,
                "What is the price?",
                client=self.client,
            )

    def test_api_connection_failure_is_handled(self):
        from openai import APIConnectionError

        self.client.responses.create.side_effect = APIConnectionError(
            request=Mock(),
        )

        with self.assertRaises(AIStaffUnavailableError):
            generate_answer(
                self.organization,
                "What is the price?",
                client=self.client,
            )


    def test_sales_search_excludes_inactive_deleted_and_hidden_products(self):
        Product.objects.create(
            organization=self.organization,
            name="Inactive Router",
            is_active=False,
            show_on_whatsapp=True,
        )

        Product.objects.create(
            organization=self.organization,
            name="Deleted Router",
            is_active=True,
            show_on_whatsapp=True,
            deleted_at=__import__("django.utils.timezone", fromlist=["now"]).now(),
        )

        Product.objects.create(
            organization=self.organization,
            name="WhatsApp Hidden Router",
            is_active=True,
            show_on_whatsapp=False,
        )

        results = search_organization_products(self.organization, "Router")

        self.assertEqual(results, [])




@override_settings(
    STORAGES={
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
)
class AIAssistantViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="ai_test_user",
            password="test-password-not-for-production",
        )

        cls.organization_a = Organization.objects.create(
            name="AI View Organization A",
            status="active",
        )
        cls.organization_b = Organization.objects.create(
            name="AI View Organization B",
            status="active",
        )

        OrganizationMember.objects.create(
            organization=cls.organization_a,
            user=cls.user,
            role="owner",
            is_active=True,
        )
        OrganizationMember.objects.create(
            organization=cls.organization_b,
            user=cls.user,
            role="owner",
            is_active=True,
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("product_knowledge:ai_assistant")

    def test_multiple_memberships_require_organization_selection(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select an organization")
        self.assertFalse(response.context["can_ask"])
        self.assertIsNone(response.context["organization"])

    def test_user_can_select_an_authorized_organization(self):
        response = self.client.post(
            self.url,
            {
                "action": "select_organization",
                "organization_id": str(self.organization_b.pk),
            },
        )

        self.assertRedirects(response, self.url)
        self.assertEqual(
            self.client.session["ai_active_organization_id"],
            self.organization_b.pk,
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["organization"],
            self.organization_b,
        )
        self.assertTrue(response.context["can_ask"])

    def test_user_cannot_select_an_organization_without_membership(self):
        other_organization = Organization.objects.create(
            name="Unauthorized AI Organization",
            status="active",
        )

        response = self.client.post(
            self.url,
            {
                "action": "select_organization",
                "organization_id": str(other_organization.pk),
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertNotIn(
            "ai_active_organization_id",
            self.client.session,
        )

    @patch("product_knowledge.views.generate_answer")
    def test_question_uses_selected_organization(self, mock_generate_answer):
        self.client.post(
            self.url,
            {
                "action": "select_organization",
                "organization_id": str(self.organization_b.pk),
            },
        )

        mock_generate_answer.return_value = {
            "answer": "This is a mocked answer.",
            "model": "test-model",
            "sources": {
                "products": [],
                "documents": [],
                "categories": [],
            },
        }

        response = self.client.post(
            self.url,
            {"question": "What services do we provide?"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This is a mocked answer.")
        mock_generate_answer.assert_called_once_with(
            self.organization_b,
            "What services do we provide?",
            can_access_admin_only=True,
        )

    def test_user_without_active_membership_cannot_ask_ai(self):
        user_without_membership = User.objects.create_user(
            username="ai_no_membership_user",
            password="test-password-not-for-production",
        )
        self.client.force_login(user_without_membership)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["can_ask"])
        self.assertIsNone(response.context["organization"])




class AISalesProductSearchTests(TestCase):
    """Test organization isolation and visibility for AI sales search."""

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(
            name="AI Sales Test Organization",
            organization_type="business",
            status="active",
        )

        cls.other_organization = Organization.objects.create(
            name="Other AI Sales Organization",
            organization_type="business",
            status="active",
        )

    def create_product(self, name, organization=None, **kwargs):
        data = {
            "organization": (
                organization
                if organization is not None
                else self.organization
            ),
            "name": name,
            "is_active": True,
            "show_on_whatsapp": True,
            "price": "150000.00",
            "cost_price": "90000.00",
            "currency": "TZS",
        }
        data.update(kwargs)
        return Product.objects.create(**data)

    def test_returns_matching_active_product(self):
        product = self.create_product("Network Router")

        results = search_organization_products(
            self.organization,
            "Network Router",
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], product.pk)
        self.assertEqual(results[0]["price"], "150000.00")

    def test_excludes_other_organization_products(self):
        self.create_product(
            "Private Network Router",
            organization=self.other_organization,
        )

        results = search_organization_products(
            self.organization,
            "Network Router",
        )

        self.assertEqual(results, [])

    def test_excludes_inactive_products(self):
        self.create_product(
            "Inactive Router",
            is_active=False,
        )

        results = search_organization_products(
            self.organization,
            "Router",
        )

        self.assertEqual(results, [])

    def test_excludes_whatsapp_hidden_products(self):
        self.create_product(
            "Hidden Router",
            show_on_whatsapp=False,
        )

        results = search_organization_products(
            self.organization,
            "Router",
        )

        self.assertEqual(results, [])

    def test_excludes_soft_deleted_products(self):
        from django.utils import timezone

        self.create_product(
            "Deleted Router",
            deleted_at=timezone.now(),
        )

        results = search_organization_products(
            self.organization,
            "Router",
        )

        self.assertEqual(results, [])

    def test_never_returns_internal_cost_price(self):
        self.create_product("Network Router")

        results = search_organization_products(
            self.organization,
            "Router",
        )

        self.assertEqual(len(results), 1)
        self.assertNotIn("cost_price", results[0])
        self.assertNotIn("wholesale_price", results[0])
        self.assertEqual(results[0]["price"], "150000.00")

    def test_empty_query_returns_no_products(self):
        self.create_product("Network Router")

        results = search_organization_products(
            self.organization,
            "",
        )

        self.assertEqual(results, [])

    def test_searches_product_specifications(self):
        self.create_product(
            "Wireless Router",
            specifications={
                "wireless_standard": "Wi-Fi 6",
                "frequency": "5GHz",
            },
        )

        results = search_organization_products(
            self.organization,
            "Wi-Fi 6",
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Wireless Router")

    def test_searches_additional_information(self):
        self.create_product(
            "Network Router",
            additional_information={
                "feature": "parental control",
            },
        )

        results = search_organization_products(
            self.organization,
            "parental control",
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Network Router")

    def test_specific_brand_and_product_query_excludes_incidental_match(self):
        switch = self.create_product(
            "TP-Link TL-SG108 Network Switch",
            brand="TP-Link",
            model="TL-SG108",
            description="An 8-port Gigabit Ethernet switch for network connections.",
        )
        self.create_product(
            "Wi-Fi Router",
            brand="Generic",
            description="Wireless internet router for home and office.",
        )

        results = search_organization_products(
            self.organization,
            "Show me available TP-Link network switches",
        )

        self.assertEqual([item["id"] for item in results], [switch.pk])

    def test_short_specific_product_query_still_returns_match(self):
        router = self.create_product(
            "Wi-Fi Router",
            description="Wireless internet router for home and office.",
        )

        results = search_organization_products(self.organization, "Wi-Fi router")

        self.assertEqual([item["id"] for item in results], [router.pk])

    def test_context_recognizes_product_names_without_sales_keywords(self):
        from .context import _is_product_question

        self.create_product(
            "Wi-Fi Router",
            brand="Generic",
            description="Wireless internet router for home and office.",
        )
        self.create_product(
            "TP-Link TL-SG108 Network Switch",
            brand="TP-Link",
            model="TL-SG108",
        )

        self.assertTrue(
            _is_product_question("Wi-Fi router", self.organization)
        )
        self.assertTrue(
            _is_product_question("Show me Wi-Fi routers", self.organization)
        )
        self.assertTrue(
            _is_product_question(
                "TP-Link TL-SG108 Network Switch",
                self.organization,
            )
        )
        self.assertTrue(
            _is_product_question(
                "Show me available TP-Link network switches",
                self.organization,
            )
        )

    def test_context_does_not_match_products_from_another_organization(self):
        from .context import _is_product_question

        self.create_product(
            "Wi-Fi Router",
            organization=self.other_organization,
        )

        self.assertFalse(
            _is_product_question("Wi-Fi router", self.organization)
        )

    def test_context_keeps_company_questions_out_of_product_retrieval(self):
        from .context import _is_product_question

        self.create_product("Wi-Fi Router")

        self.assertFalse(
            _is_product_question(
                "What is Faltasi's mission and core values?",
                self.organization,
            )
        )
        self.assertFalse(
            _is_product_question(
                "Explain the platform architecture and modules.",
                self.organization,
            )
        )

    def test_returns_only_customer_appropriate_price_fields(self):
        self.create_product(
            "Network Router",
            price="150000.00",
            cost_price="90000.00",
            wholesale_price="110000.00",
        )

        results = search_organization_products(
            self.organization,
            "Router",
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["price"], "150000.00")

        self.assertNotIn("cost_price", results[0])
        self.assertNotIn("wholesale_price", results[0])
        self.assertNotIn("profit", results[0])
