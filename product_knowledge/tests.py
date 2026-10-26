
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
    search_products,
    search_document_chunks,
    get_request_categories,
    retrieve_knowledge,
)

from .context import (
    MAX_CONTEXT_CHARS,
    build_knowledge_context,
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



from products.models import Product
from business_requests.models import (
    Department,
    RequestCategory,
    RequestField,
)
from .search import (
    search_products,
    search_document_chunks,
    get_request_categories,
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

        results = search_products(
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

        results = search_products(
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

        results = search_products(
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
            search_products(self.organization, ""),
            [],
        )

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
