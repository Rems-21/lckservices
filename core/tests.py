"""
Suite complète de tests fonctionnels et techniques — Plateforme LCK Services SARL.
Vérifie :
1. Rôle unique 'Utilisateur' & droits d'administration des comptes + journalisation AuditLog.
2. Calcul automatique du volume m³ (L×l×H) et conversion multi-devises vers FCFA.
3. Moteur de répartition des dépenses (Volume, Poids, Valeur, Forfait + Ajustement manuel + Marge).
4. Facturation automatique Proforma/Définitive, conversion, paiements partiels/totaux et soldes.
5. Verrouillage des livraisons sur facture impayée et déblocage sur autorisation de livraison à crédit.
6. Génération PDF (Facture, Reçu, Manifeste, Bon de Livraison, Rapport), Export Excel OpenPyXL et Sauvegarde ZIP.
"""
from datetime import timedelta
from decimal import Decimal
from django.test import Client as WebClient, TestCase
from django.urls import reverse
from django.utils import timezone
from accounts.models import AuditLog, User
from accounts.services import create_full_backup
from billing.models import CreditDeliveryAuthorization, Invoice, Payment
from billing.services import convert_proforma_to_definitive, generate_folder_invoices
from cargo.models import CargoCategory, Parcel
from clients.models import Client
from core.models import Currency
from finance.models import ExpenseCategory, FolderExpense
from finance.services import save_folder_allocation_run
from logistics.forms import DeliveryForm
from logistics.models import Delivery
from shipments.models import Location, ShipmentFolder


class LCKPlatformTests(TestCase):
    def setUp(self):
        self.fcfa = Currency.objects.create(code="FCFA", name="Franc CFA", rate_to_fcfa=Decimal("1.0000"), is_base=True)
        self.usd = Currency.objects.create(code="USD", name="Dollar US", rate_to_fcfa=Decimal("600.0000"), is_base=False)

        self.user_admin = User.objects.create_user(
            username="admin_test",
            password="Password123!",
            first_name="Jean",
            last_name="Admin",
            is_access_admin=True,
        )
        self.user_std = User.objects.create_user(
            username="agent_test",
            password="Password123!",
            first_name="Marie",
            last_name="Agent",
            is_access_admin=False,
        )

        self.origin = Location.objects.create(code="CNNSA", name="Guangzhou Nansha", city="Guangzhou", country="Chine", location_type="PORT")
        self.dest = Location.objects.create(code="CMDLA", name="Port de Douala", city="Douala", country="Cameroun", location_type="PORT")

        self.client_a = Client.objects.create(name="Client Alpha SARL", phone="+237690000001", city="Douala")
        self.client_b = Client.objects.create(name="Client Beta Ets", phone="+237690000002", city="Yaoundé")

        self.cat_cargo = CargoCategory.objects.create(name="Électronique")
        self.cat_exp = ExpenseCategory.objects.create(name="Fret Maritime")

        self.folder = ShipmentFolder.objects.create(
            transport_mode="MARITIME",
            origin=self.origin,
            destination=self.dest,
            bl_number="BL-TEST-001",
            container_number="MSCU1234567",
            created_by=self.user_admin,
        )

    def test_single_functional_role_and_audit_login(self):
        self.assertEqual(self.user_admin.role_label, "Utilisateur")
        self.assertEqual(self.user_std.role_label, "Utilisateur")
        self.assertTrue(self.user_admin.can_manage_accounts)
        self.assertFalse(self.user_std.can_manage_accounts)

        web = WebClient()
        logged = web.login(username="agent_test", password="Password123!")
        self.assertTrue(logged)
        self.assertTrue(AuditLog.objects.filter(action="LOGIN", username_snapshot="agent_test").exists())

        # Un utilisateur standard accède à tous les modules métiers
        for route in ["reports:dashboard", "clients:list", "shipments:list", "cargo:list", "finance:expense_list", "billing:invoice_list"]:
            resp = web.get(reverse(route))
            self.assertEqual(resp.status_code, 200)

    def test_parcel_volume_cbm_and_currency_conversion(self):
        # 10 cartons de 100cm x 50cm x 40cm = 10 * 0.2 m³ = 2.0000 m³
        parcel = Parcel.objects.create(
            folder=self.folder,
            client=self.client_a,
            category=self.cat_cargo,
            description="Écrans LED",
            quantity=10,
            weight_kg=Decimal("250.000"),
            length_cm=Decimal("100"),
            width_cm=Decimal("50"),
            height_cm=Decimal("40"),
            declared_value=Decimal("1000.00"),
            declared_currency=self.usd,
        )
        self.assertTrue(parcel.parcel_code.startswith("COL-"))
        self.assertEqual(parcel.volume_cbm, Decimal("2.0000"))
        self.assertEqual(parcel.declared_value_fcfa, Decimal("600000.00"))

    def test_expense_allocation_margin_invoicing_payment_and_credit_delivery(self):
        # Colis A : 3 m³, Colis B : 1 m³ (Total = 4 m³ -> 75% / 25%)
        p_a = Parcel.objects.create(
            folder=self.folder,
            client=self.client_a,
            description="Lot A",
            quantity=3,
            weight_kg=Decimal("300"),
            length_cm=Decimal("100"),
            width_cm=Decimal("100"),
            height_cm=Decimal("100"),
            declared_value=Decimal("500"),
            declared_currency=self.fcfa,
        )
        p_b = Parcel.objects.create(
            folder=self.folder,
            client=self.client_b,
            description="Lot B",
            quantity=1,
            weight_kg=Decimal("100"),
            length_cm=Decimal("100"),
            width_cm=Decimal("100"),
            height_cm=Decimal("100"),
            declared_value=Decimal("200"),
            declared_currency=self.fcfa,
        )

        # Dépense en USD : 1000 USD * 600 = 600 000 FCFA + 200 000 FCFA douane = 800 000 FCFA
        FolderExpense.objects.create(
            folder=self.folder,
            category=self.cat_exp,
            label="Fret",
            amount_original=Decimal("1000.00"),
            currency=self.usd,
        )
        FolderExpense.objects.create(
            folder=self.folder,
            category=self.cat_exp,
            label="Douane",
            amount_original=Decimal("200000.00"),
            currency=self.fcfa,
        )
        self.assertEqual(self.folder.total_expenses_fcfa, Decimal("800000.00"))

        # Répartition au volume + marge 25%
        run = save_folder_allocation_run(
            folder=self.folder,
            allocation_method="VOLUME",
            margin_type="PERCENT",
            margin_value=Decimal("25.00"),
            user=self.user_admin,
        )
        p_a.refresh_from_db()
        p_b.refresh_from_db()
        self.assertEqual(p_a.allocated_cost_fcfa, Decimal("600000.00"))
        self.assertEqual(p_b.allocated_cost_fcfa, Decimal("200000.00"))
        self.assertEqual(p_a.suggested_price_fcfa, Decimal("750000.00"))
        self.assertEqual(p_b.suggested_price_fcfa, Decimal("250000.00"))
        self.assertEqual(run.expected_profit_fcfa, Decimal("200000.00"))

        # Génération Proforma puis conversion en Définitive pour Client A
        proformas = generate_folder_invoices(self.folder, invoice_type="PROFORMA", client_id=self.client_a.id, user=self.user_admin)
        self.assertEqual(len(proformas), 1)
        definitive_a = convert_proforma_to_definitive(proformas[0], user=self.user_admin)
        self.assertEqual(definitive_a.total_amount_fcfa, Decimal("750000.00"))
        self.assertEqual(definitive_a.status, "EMISE")

        # Tentative de livraison sans paiement ni autorisation crédit -> BLOQUÉE
        blocked_form = DeliveryForm(
            data={
                "folder": self.folder.id,
                "client": self.client_a.id,
                "parcels": [p_a.id],
                "invoice": definitive_a.id,
                "delivery_mode": "ENLEVEMENT_ENTREPOT",
                "recipient_name": "Réceptionnaire Test",
                "delivered_at": timezone.now().strftime("%Y-%m-%dT%H:%M"),
            }
        )
        self.assertFalse(blocked_form.is_valid())

        # Paiement partiel de 250 000 FCFA -> Solde restant 500 000 FCFA
        pay_partial = Payment.objects.create(
            invoice=definitive_a,
            client=self.client_a,
            amount_fcfa=Decimal("250000.00"),
            payment_method="MOBILE_MONEY",
            received_by=self.user_std,
        )
        definitive_a.refresh_from_db()
        self.assertEqual(definitive_a.status, "PARTIELLEMENT_PAYEE")
        self.assertEqual(definitive_a.balance_due_fcfa, Decimal("500000.00"))

        # Octroi d'une autorisation de livraison à crédit -> Livraison AUTORISÉE
        credit_auth = CreditDeliveryAuthorization.objects.create(
            client=self.client_a,
            invoice=definitive_a,
            folder=self.folder,
            authorized_balance_fcfa=definitive_a.balance_due_fcfa,
            promised_due_date=timezone.localdate() + timedelta(days=15),
            reason="Accord direction",
            approved_by=self.user_admin,
        )
        allowed_form = DeliveryForm(
            data={
                "folder": self.folder.id,
                "client": self.client_a.id,
                "parcels": [p_a.id],
                "invoice": definitive_a.id,
                "credit_authorization": credit_auth.id,
                "delivery_mode": "ENLEVEMENT_ENTREPOT",
                "recipient_name": "Réceptionnaire Test",
                "delivered_at": timezone.now().strftime("%Y-%m-%dT%H:%M"),
            }
        )
        self.assertTrue(allowed_form.is_valid(), allowed_form.errors)
        delivery = allowed_form.save()
        delivery.parcels.set([p_a])

        # Vérification des exports PDF, Excel, QR et Backup ZIP
        web = WebClient()
        web.login(username="admin_test", password="Password123!")

        for pdf_url in [
            reverse("documents:invoice_pdf", args=[definitive_a.id]),
            reverse("documents:receipt_pdf", args=[pay_partial.id]),
            reverse("documents:manifest_pdf", args=[self.folder.id]),
            reverse("documents:delivery_note_pdf", args=[delivery.id]),
            reverse("documents:parcel_label_pdf", args=[p_a.id]),
            reverse("reports:export_pdf"),
        ]:
            res = web.get(pdf_url)
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res["Content-Type"], "application/pdf")
            self.assertTrue(res.content.startswith(b"%PDF"))

        xlsx_res = web.get(reverse("reports:export_excel"))
        self.assertEqual(xlsx_res.status_code, 200)
        self.assertIn("spreadsheetml", xlsx_res["Content-Type"])

        qr_res = web.get(reverse("documents:verify_qr", kwargs={"doc_kind": "facture", "token": str(definitive_a.verification_token)}))
        self.assertEqual(qr_res.status_code, 200)
        self.assertContains(qr_res, definitive_a.number)

        # Vérification du rendu HTML complet de toutes les vues des modules
        all_views = [
            reverse("accounts:profile"),
            reverse("accounts:user_list"),
            reverse("accounts:user_create"),
            reverse("accounts:audit_list"),
            reverse("accounts:settings_backups"),
            reverse("clients:list"),
            reverse("clients:create"),
            reverse("clients:detail", args=[self.client_a.id]),
            reverse("shipments:list"),
            reverse("shipments:create"),
            reverse("shipments:locations"),
            reverse("shipments:detail", args=[self.folder.id]),
            reverse("cargo:list"),
            reverse("cargo:create"),
            reverse("cargo:categories"),
            reverse("cargo:detail", args=[p_a.id]),
            reverse("logistics:hub"),
            reverse("logistics:warehouse"),
            reverse("logistics:delivery_list"),
            reverse("logistics:delivery_create"),
            reverse("logistics:delivery_detail", args=[delivery.id]),
            reverse("logistics:incident_list"),
            reverse("logistics:incident_create"),
            reverse("finance:expense_list"),
            reverse("finance:expense_create"),
            reverse("finance:categories"),
            reverse("finance:allocate_folder", args=[self.folder.id]),
            reverse("finance:allocation_history"),
            reverse("finance:allocation_detail", args=[run.id]),
            reverse("billing:invoice_list"),
            reverse("billing:invoice_create"),
            reverse("billing:invoice_detail", args=[definitive_a.id]),
            reverse("billing:payment_list"),
            reverse("billing:receivables"),
            reverse("documents:list"),
            reverse("communications:hub"),
            reverse("communications:templates"),
            reverse("reports:dashboard"),
            reverse("reports:hub"),
            reverse("reports:global_search") + "?q=MAR",
        ]
        for view_url in all_views:
            page_res = web.get(view_url)
            self.assertEqual(page_res.status_code, 200, f"Échec de rendu sur {view_url}")

        bkp = create_full_backup(user=self.user_admin, include_media=False, notes="Test unitaire")
        self.assertTrue(bkp.size_bytes > 0)

    def test_mtsarl_groupage_cockpit_workflow(self):
        """Vérifie le workflow tout-en-un style MTsarl : création rapide dossier, ajout multi-articles, encaissement colis, livraison à crédit, fiche d'impression et facture partagée WhatsApp."""
        web = WebClient()
        web.login(username="agent_test", password="Password123!")

        # 1. Création rapide d'un dossier via modale (#newDossierModal)
        resp_create = web.post(
            reverse("shipments:quick_create"),
            {
                "transport_mode": "MARITIME",
                "origin_port": "Ningbo (Chine)",
                "destination_port": "Douala (Cameroun)",
                "container_type": "40HC",
                "container_number": "COSU9988776",
                "vessel_name": "COSCO SHIPPING",
                "forwarder": "Sinotrans Ningbo",
                "bl_number": "COSCO-NB-5501",
                "departure_date": "2026-10-15",
                "arrival_estimated_date": "2026-11-20",
            },
        )
        self.assertEqual(resp_create.status_code, 302)
        new_folder = ShipmentFolder.objects.filter(container_number="COSU9988776").first()
        self.assertIsNotNone(new_folder)
        self.assertEqual(new_folder.forwarder, "Sinotrans Ningbo")

        # 2. Ajout multi-articles avec création de client à la volée + facturation automatique
        resp_items = web.post(
            reverse("shipments:add_items", args=[new_folder.id]),
            {
                "client_type": "new",
                "new_client_name": "STE HORIZON IMPORT",
                "new_client_phone": "+237 695 11 22 33",
                "new_client_city": "Douala",
                "item_description[]": ["Groupes électrogènes insonorisés", "Panneaux solaires monocristallins"],
                "item_type[]": ["MARCHANDISE", "MARCHANDISE"],
                "item_chassis[]": ["", ""],
                "item_category[]": [str(self.cat_cargo.id), str(self.cat_cargo.id)],
                "item_qty[]": ["2", "10"],
                "item_length[]": ["100", "100"],
                "item_width[]": ["100", "50"],
                "item_height[]": ["100", "20"],
                "item_volume[]": ["0", "0"],
                "item_weight[]": ["450", "220"],
                "item_declared_val[]": ["3000", "1500"],
                "item_currency[]": [str(self.usd.id), str(self.usd.id)],
                "item_cost_share[]": ["500000", "250000"],
                "item_notes[]": ["Fragile", "Palette filmée"],
            },
        )
        self.assertEqual(resp_items.status_code, 302)
        parcels = list(new_folder.parcels.order_by("id"))
        self.assertEqual(len(parcels), 2)
        p1, p2 = parcels[0], parcels[1]
        self.assertEqual(p1.volume_cbm, Decimal("2.0000"))
        self.assertEqual(p2.volume_cbm, Decimal("1.0000"))

        inv = Invoice.objects.filter(folder=new_folder, invoice_type="DEFINITIVE").first()
        self.assertIsNotNone(inv)
        self.assertEqual(inv.total_amount_fcfa, Decimal("750000.00"))

        # 3. Encaissement partiel sur le 1er colis (200 000 FCFA sur 500 000 FCFA)
        resp_pay = web.post(
            reverse("shipments:pay_item", args=[new_folder.id, p1.id]),
            {
                "amount_fcfa": "200000",
                "payment_method": "MOBILE_MONEY",
                "reference": "MOMO-774411",
                "notes": "Acompte client",
            },
        )
        self.assertEqual(resp_pay.status_code, 302)
        p1.refresh_from_db()
        self.assertEqual(p1.paid_amount_fcfa, Decimal("200000.00"))
        self.assertEqual(p1.balance_due_fcfa, Decimal("300000.00"))

        # 4. Livraison bloquée sans autorisation de crédit
        resp_deliv_blocked = web.post(
            reverse("shipments:deliver_item", args=[new_folder.id, p1.id]),
            {"recipient_name": "Agent Réception"},
        )
        self.assertEqual(resp_deliv_blocked.status_code, 302)
        p1.refresh_from_db()
        self.assertNotEqual(p1.status, "LIVRE")

        # 5. Livraison autorisée avec octroi de crédit + échéance
        due_iso = (timezone.localdate() + timedelta(days=10)).strftime("%Y-%m-%d")
        resp_deliv_ok = web.post(
            reverse("shipments:deliver_item", args=[new_folder.id, p1.id]),
            {
                "recipient_name": "Agent Réception",
                "delivery_mode": "ENLEVEMENT_ENTREPOT",
                "authorize_credit": "1",
                "promised_due_date": due_iso,
                "credit_reason": "Client sous contrat cadre",
            },
        )
        self.assertEqual(resp_deliv_ok.status_code, 302)
        p1.refresh_from_db()
        self.assertEqual(p1.status, "LIVRE")
        self.assertTrue(Delivery.objects.filter(folder=new_folder, parcels=p1).exists())
        self.assertTrue(CreditDeliveryAuthorization.objects.filter(folder=new_folder, status="ACTIVE").exists())

        # 6. Fiche d'impression dossier, facture partagée WhatsApp (HTML + PDF), API recherche & notifications, alias URLs
        self.assertEqual(web.get(reverse("shipments:print_fiche", args=[new_folder.id])).status_code, 200)

        anon = WebClient()
        share_url = f"{reverse('billing:shared_invoice')}?item={p1.id}&token={p1.share_token}"
        share_res = anon.get(share_url)
        self.assertEqual(share_res.status_code, 200)
        self.assertContains(share_res, p1.parcel_code)

        share_pdf = anon.get(share_url + "&download=pdf")
        self.assertEqual(share_pdf.status_code, 200)
        self.assertEqual(share_pdf["Content-Type"], "application/pdf")

        api_search = web.get(reverse("reports:search_api") + "?q=COSU")
        self.assertEqual(api_search.status_code, 200)
        self.assertTrue(len(api_search.json().get("groups", [])) >= 1)

        self.assertEqual(web.get(reverse("reports:notifications")).status_code, 200)
        self.assertEqual(web.get(reverse("reports:notifications_count_api")).status_code, 200)
        self.assertEqual(web.get("/groupage/").status_code, 200)
        self.assertEqual(web.get("/accounting/groupage/").status_code, 200)
