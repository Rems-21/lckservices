"""
Commande d'initialisation de la plateforme LCK Services SARL :
python manage.py init_lck --with-demo
"""
from datetime import timedelta
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from accounts.models import User
from billing.models import CreditDeliveryAuthorization, Payment
from billing.services import generate_folder_invoices, sync_or_create_parcel_invoice
from cargo.models import CargoCategory, Parcel
from clients.models import Client, ClientContact
from communications.models import MessageTemplate
from core.models import CompanySetting, Currency
from finance.models import ExpenseCategory, FolderExpense
from finance.services import save_folder_allocation_run
from logistics.models import TrackingEvent, WarehouseOperation
from shipments.models import Location, ShipmentFolder


class Command(BaseCommand):
    help = "Initialise le compte administrateur d'accès, les référentiels métiers, devises, modèles WhatsApp et données de démonstration."

    def add_arguments(self, parser):
        parser.add_argument(
            "--with-demo",
            action="store_true",
            help="Ajoute un jeu de données réaliste de démonstration (clients, dossiers maritime/aérien, colis, dépenses, factures).",
        )
        parser.add_argument(
            "--reset-demo",
            action="store_true",
            help="Purge les dossiers/clients de démonstration existants avant de recréer le jeu de démonstration proprement.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        # 1. Paramètres société
        company = CompanySetting.get_solo()
        company.niu = company.niu or "M012600045892X"
        company.rccm = company.rccm or "RC/DLA/2026/B/1420"
        company.bank_details = (
            company.bank_details
            or "Afriland First Bank : 10005 00001 09876543210 42 | Orange Money / MTN MoMo Marchand : LCK SERVICES"
        )
        company.save()

        # 2. Devises (FCFA base + USD, EUR, CNY)
        currencies_data = [
            ("FCFA", "Franc CFA", "FCFA", Decimal("1.0000"), True),
            ("EUR", "Euro", "€", Decimal("655.9570"), False),
            ("USD", "Dollar Américain", "USD", Decimal("610.0000"), False),
            ("CNY", "Yuan Chinois (RMB)", "¥", Decimal("85.0000"), False),
        ]
        currencies = {}
        for code, name, sym, rate, is_base in currencies_data:
            cur, _ = Currency.objects.update_or_create(
                code=code,
                defaults={"name": name, "symbol": sym, "rate_to_fcfa": rate, "is_base": is_base, "is_active": True},
            )
            currencies[code] = cur

        # 3. Compte administrateur initial (Section 3) + agent opérationnel
        admin_user, created_admin = User.objects.get_or_create(
            username="admin",
            defaults={
                "first_name": "Administrateur",
                "last_name": "LCK",
                "email": "admin@lckservices.com",
                "phone": "+237 699 00 11 22",
                "job_title": "Gestionnaire des Accès & Opérations",
                "is_access_admin": True,
                "is_staff": True,
                "is_superuser": True,
                "is_active": True,
            },
        )
        if created_admin:
            admin_user.set_password("LckAdmin2026!")
            admin_user.save()

        agent_user, created_agent = User.objects.get_or_create(
            username="agent",
            defaults={
                "first_name": "Clarisse",
                "last_name": "Ndjock",
                "email": "operations@lckservices.com",
                "phone": "+237 677 44 55 66",
                "job_title": "Chargée de Transit & Groupage",
                "is_access_admin": False,
                "is_active": True,
            },
        )
        if created_agent:
            agent_user.set_password("LckAgent2026!")
            agent_user.save()

        # 4. Ports et Aéroports
        locations_data = [
            ("CNNSA", "Port de Guangzhou Nansha", "Guangzhou", "Chine", "PORT"),
            ("CNNGB", "Port de Ningbo-Zhoushan (Yiwu)", "Ningbo", "Chine", "PORT"),
            ("CAN", "Aéroport Guangzhou Baiyun", "Guangzhou", "Chine", "AEROPORT"),
            ("AEJEA", "Port de Jebel Ali", "Dubaï", "Émirats Arabes Unis", "PORT"),
            ("DXB", "Aéroport International de Dubaï", "Dubaï", "Émirats Arabes Unis", "AEROPORT"),
            ("IST", "Aéroport d'Istanbul Cargo", "Istanbul", "Turquie", "AEROPORT"),
            ("CDG", "Aéroport Paris-Charles de Gaulle", "Paris", "France", "AEROPORT"),
            ("CMDLA", "Port Autonome de Douala", "Douala", "Cameroun", "PORT"),
            ("CMKBI", "Port Autonome de Kribi", "Kribi", "Cameroun", "PORT"),
            ("DLA", "Aéroport International de Douala", "Douala", "Cameroun", "AEROPORT"),
            ("NSI", "Aéroport International Yaoundé-Nsimalen", "Yaoundé", "Cameroun", "AEROPORT"),
        ]
        locs = {}
        for code, name, city, country, ltype in locations_data:
            loc, _ = Location.objects.get_or_create(
                code=code,
                defaults={"name": name, "city": city, "country": country, "location_type": ltype},
            )
            locs[code] = loc

        # 5. Catégories de marchandises
        cargo_cats_data = [
            ("Électronique & Téléphonie", "HS-85", True, "Équipements sensibles nécessitant manutention soignée"),
            ("Textile, Prêt-à-porter & Chaussures", "HS-62", False, "Ballots et cartons d'habillement"),
            ("Pièces détachées automobiles", "HS-87", False, "Pièces mécaniques et accessoires"),
            ("Mobilier, Luminaires & Décoration", "HS-94", True, "Meubles, verrerie et articles fragiles"),
            ("Cosmétiques & Produits d'entretien", "HS-33", False, "Produits de beauté et hygiène"),
            ("Quincaillerie & Matériaux BTP", "HS-73", False, "Outillage, robinetterie et équipements"),
        ]
        cargo_cats = {}
        for name, code, fragile, desc in cargo_cats_data:
            cat, _ = CargoCategory.objects.get_or_create(
                name=name,
                defaults={"code": code, "is_fragile_or_special": fragile, "description": desc},
            )
            cargo_cats[code] = cat

        # 6. Catégories de dépenses
        exp_cats_data = [
            ("Fret Maritime International", "FRET-MAR", "Fret conteneur compagnie maritime"),
            ("Fret Aérien International", "FRET-AER", "Fret compagnie aérienne LTA/AWB"),
            ("Manutention & Empotage Origine", "MAN-ORG", "Frais d'entrepôt, groupage et chargement à l'origine"),
            ("Droits & Taxes de Douane", "DOUANE", "Liquidation douanière et taxes à l'importation"),
            ("Frais Portuaires / Aéroportuaires", "PAD-ADC", "Acconage, relevage, magasinage port/aéroport"),
            ("Transport Local & Livraison", "TRP-LOC", "Traction conteneur et camionnage vers entrepôt LCK"),
            ("Frais Administratifs & Divers", "DIV", "Frais de dossier, BESC, SGS et divers"),
        ]
        exp_cats = {}
        for name, code, desc in exp_cats_data:
            ec, _ = ExpenseCategory.objects.get_or_create(
                name=name,
                defaults={"code": code, "description": desc},
            )
            exp_cats[code] = ec

        # 7. Modèles de messages WhatsApp
        templates_data = [
            (
                "reception-origine",
                "Confirmation de réception colis à l'origine",
                "RECEPTION",
                "Bonjour {client_nom},\nNous vous confirmons la bonne réception de votre colis *{colis_code}* ({volume_m3} m³ / {poids_kg} kg) dans notre entrepôt de {origine}, rattaché au dossier *{dossier_ref}* ({mode_transport}).\nSuivi en ligne : {lien_document}\nMerci de votre confiance — *{societe}*",
            ),
            (
                "avis-arrivee",
                "Avis d'arrivée et disponibilité en entrepôt",
                "ARRIVEE",
                "Bonjour {client_nom},\nBonne nouvelle ! Les marchandises du dossier *{dossier_ref}* ({mode_transport} {origine} -> {destination}) sont arrivées et disponibles pour retrait/livraison dans nos locaux.\nCordialement,\n*{societe}*",
            ),
            (
                "envoi-facture",
                "Envoi de facture et situation de règlement",
                "FACTURATION",
                "Bonjour {client_nom},\nVeuillez trouver les références de votre facture *{facture_num}* relative au dossier *{dossier_ref}* :\n• Net à payer : *{montant_total}*\n• Déjà réglé : {montant_paye}\n• Solde restant : *{solde_restant}*\nLien de vérification : {lien_document}\nMerci — *{societe}*",
            ),
            (
                "relance-impaye",
                "Relance aimable de solde client",
                "RELANCE",
                "Bonjour {client_nom},\nSauf erreur ou omission de notre part, votre facture *{facture_num}* (Dossier {dossier_ref}) présente un solde restant de *{solde_restant}*.\nNous vous remercions de bien vouloir procéder à sa régularisation.\nService Comptabilité — *{societe}*",
            ),
            (
                "livraison-confirmee",
                "Confirmation de remise / livraison",
                "LIVRAISON",
                "Bonjour {client_nom},\nNous vous confirmons la livraison effective de vos colis du dossier *{dossier_ref}*. Toute l'équipe de *{societe}* vous remercie pour votre fidélité !",
            ),
        ]
        for code, name, cat, body in templates_data:
            MessageTemplate.objects.get_or_create(
                code=code,
                defaults={"name": name, "category": cat, "body_template": body, "is_active": True},
            )

        # 8. Données de démonstration réalistes si demandé et si aucun dossier n'existe encore
        if options.get("reset_demo"):
            from billing.models import Invoice
            Payment.objects.all().delete()
            CreditDeliveryAuthorization.objects.all().delete()
            Invoice.objects.all().delete()
            ShipmentFolder.objects.all().delete()
            Client.objects.all().delete()

        if options["with_demo"] and ShipmentFolder.objects.count() == 0:
            today = timezone.localdate()

            c1 = Client.objects.create(
                client_type="ENTREPRISE",
                name="ETS KAMGA DISTRIBUTION",
                tax_id="M082112345678A",
                phone="+237 699 12 34 56",
                whatsapp="+237 699 12 34 56",
                email="direction@kamgadistrib.cm",
                address="Marché Mboppi, Avenue Kennedy",
                city="Douala",
                country="Cameroun",
                credit_allowed=True,
                credit_limit_fcfa=Decimal("3000000.00"),
            )
            ClientContact.objects.create(
                client=c1,
                full_name="Hervé Kamga",
                role="Gérant",
                phone="+237 699 12 34 56",
                is_primary=True,
            )

            c2 = Client.objects.create(
                client_type="ENTREPRISE",
                name="MAISON ÉLÉGANCE SARL",
                tax_id="M042298765432B",
                phone="+237 675 88 99 00",
                whatsapp="+237 675 88 99 00",
                email="achats@maisonelegance.cm",
                address="Akwa Boulevard de la Liberté",
                city="Douala",
                country="Cameroun",
            )

            c3 = Client.objects.create(
                client_type="PARTICULIER",
                name="M. Samuel Tchoumi",
                phone="+237 691 45 67 89",
                whatsapp="+237 691 45 67 89",
                address="Bastos",
                city="Yaoundé",
                country="Cameroun",
            )

            # Dossier 1 : Groupage Maritime Guangzhou -> Douala
            f_mar = ShipmentFolder.objects.create(
                title="Campagne Groupage Conteneur 40' HC — Chine Novembre",
                transport_mode="MARITIME",
                operation_type="GROUPAGE",
                status="DISPONIBLE_ENTREPOT",
                origin=locs["CNNSA"],
                destination=locs["CMDLA"],
                forwarder="Bolloré / Agent Guangzhou",
                shipping_line="CMA CGM",
                vessel_name="CMA CGM KRIBI",
                voyage_number="0W452S",
                container_number="CMAU7845129",
                container_type="40HC",
                seal_number="SL-994821",
                bl_number="CMACGM-GZ-884120",
                etd=today - timedelta(days=32),
                atd=today - timedelta(days=31),
                eta=today - timedelta(days=3),
                ata=today - timedelta(days=2),
                default_rate_per_cbm=Decimal("240000.00"),
                created_by=admin_user,
            )

            p1 = Parcel.objects.create(
                folder=f_mar,
                client=c1,
                category=cargo_cats["HS-73"],
                description="Lots de robinetterie sanitaire et luminaires LED",
                supplier_name="Foshan Sanitary Co.",
                packaging_type="CARTON",
                quantity=25,
                weight_kg=Decimal("820.000"),
                length_cm=Decimal("60"),
                width_cm=Decimal("50"),
                height_cm=Decimal("50"),
                declared_value=Decimal("6800.00"),
                declared_currency=currencies["USD"],
                status="DISPONIBLE_ENTREPOT",
                storage_location="Zone A - Travée 02",
                created_by=admin_user,
            )
            p2 = Parcel.objects.create(
                folder=f_mar,
                client=c2,
                category=cargo_cats["HS-62"],
                description="Prêt-à-porter féminin et sacs à main",
                supplier_name="Guangzhou Fashion Hub",
                packaging_type="BALLOT",
                quantity=12,
                weight_kg=Decimal("540.000"),
                length_cm=Decimal("80"),
                width_cm=Decimal("60"),
                height_cm=Decimal("60"),
                declared_value=Decimal("32000.00"),
                declared_currency=currencies["CNY"],
                status="DISPONIBLE_ENTREPOT",
                storage_location="Zone B - Travée 01",
                created_by=agent_user,
            )

            # Dépenses multi-devises du dossier maritime
            FolderExpense.objects.create(
                folder=f_mar,
                category=exp_cats["FRET-MAR"],
                label="Fret maritime 40' HC Nansha -> Douala",
                vendor_name="CMA CGM Shipping",
                expense_date=today - timedelta(days=30),
                amount_original=Decimal("1800.00"),
                currency=currencies["USD"],
                recorded_by=admin_user,
            )
            FolderExpense.objects.create(
                folder=f_mar,
                category=exp_cats["MAN-ORG"],
                label="Empotage & manutention entrepôt Guangzhou",
                vendor_name="GZ Logistics Warehouse",
                expense_date=today - timedelta(days=32),
                amount_original=Decimal("2400.00"),
                currency=currencies["CNY"],
                recorded_by=admin_user,
            )
            FolderExpense.objects.create(
                folder=f_mar,
                category=exp_cats["DOUANE"],
                label="Dédouanement, acconage PAD & traction entrepôt Douala",
                vendor_name="Guichet Unique / PAD",
                expense_date=today - timedelta(days=2),
                amount_original=Decimal("450000.00"),
                currency=currencies["FCFA"],
                recorded_by=admin_user,
            )

            # Répartition automatique selon le volume m³ avec 30% de marge
            save_folder_allocation_run(
                folder=f_mar,
                allocation_method="VOLUME",
                margin_type="PERCENT",
                margin_value=Decimal("30.00"),
                notes="Répartition officielle au cubage m³ (marge commerciale 30%).",
                user=admin_user,
            )

            # Génération des factures définitives + paiements
            mar_invoices = generate_folder_invoices(folder=f_mar, invoice_type="DEFINITIVE", user=admin_user)
            if len(mar_invoices) >= 2:
                # Paiement intégral de la 1ère facture (p1)
                p1_line = mar_invoices[0].lines.select_related("parcel").first()
                Payment.objects.create(
                    invoice=mar_invoices[0],
                    parcel=p1_line.parcel if p1_line else p1,
                    client=mar_invoices[0].client,
                    payment_date=today - timedelta(days=1),
                    amount_fcfa=mar_invoices[0].total_amount_fcfa,
                    payment_method="VIREMENT",
                    transaction_reference="VIR-AFB-2026-8841",
                    received_by=admin_user,
                )
                # Paiement partiel de la 2e facture (p2) + autorisation crédit
                p2_line = mar_invoices[1].lines.select_related("parcel").first()
                partial_amt = (mar_invoices[1].total_amount_fcfa * Decimal("0.5")).quantize(Decimal("1."))
                Payment.objects.create(
                    invoice=mar_invoices[1],
                    parcel=p2_line.parcel if p2_line else p2,
                    client=mar_invoices[1].client,
                    payment_date=today,
                    amount_fcfa=partial_amt,
                    payment_method="MOBILE_MONEY",
                    transaction_reference="OM-99812345",
                    received_by=agent_user,
                )
                p1.refresh_from_db()
                p1.recalculate_paid_amount(save=True)
                p2.refresh_from_db()
                p2.recalculate_paid_amount(save=True)
                CreditDeliveryAuthorization.objects.create(
                    client=mar_invoices[1].client,
                    invoice=mar_invoices[1],
                    folder=f_mar,
                    authorized_balance_fcfa=mar_invoices[1].balance_due_fcfa,
                    promised_due_date=today + timedelta(days=10),
                    reason="Client fidèle sous contrat — règlement du solde sous 10 jours.",
                    approved_by=admin_user,
                )

            TrackingEvent.objects.create(
                folder=f_mar,
                stage="DEPART",
                status_before="En préparation / chargement",
                status_after="En transit international",
                location_text="Port de Guangzhou Nansha (CNNSA)",
                description="Départ navire CMA CGM KRIBI — Conteneur 40' HC CMAU7845129 scellé.",
                recorded_by=admin_user,
            )
            TrackingEvent.objects.create(
                folder=f_mar,
                stage="DISPONIBLE_ENTREPOT",
                status_before="Arrivé au port / dédouanement",
                status_after="Disponible en entrepôt",
                location_text="Entrepôt Central LCK — Douala Bonabéri",
                description="Dépotage terminé et colis mis à disposition des clients.",
                recorded_by=agent_user,
            )

            WarehouseOperation.objects.create(
                operation_type="RECEPTION_DESTINATION",
                folder=f_mar,
                warehouse_name="Entrepôt Central LCK — Douala Bonabéri",
                parcels_checked_count=37,
                total_weight_checked_kg=Decimal("1360.000"),
                condition_status="CONFORME",
                notes="Dépotage complet effectué sans avarie constatée.",
                operator=agent_user,
            )

            # Dossier 2 : Fret Aérien Express Dubaï -> Douala
            f_aer = ShipmentFolder.objects.create(
                title="Consolidation Aérienne Express — Dubaï Cargo",
                transport_mode="AERIEN",
                operation_type="GROUPAGE",
                status="EN_TRANSIT",
                origin=locs["DXB"],
                destination=locs["DLA"],
                forwarder="Al Khaleej Cargo Dubai",
                airline_name="Ethiopian Airlines Cargo",
                flight_number="ET-3915",
                awb_number="071-88451293",
                etd=today - timedelta(days=1),
                atd=today - timedelta(days=1),
                eta=today + timedelta(days=2),
                default_rate_per_kg=Decimal("6500.00"),
                created_by=agent_user,
            )
            p3 = Parcel.objects.create(
                folder=f_aer,
                client=c3,
                category=cargo_cats["HS-85"],
                description="Ordinateurs portables professionnels & équipements réseau",
                supplier_name="Al Khaleej Tech LLC",
                packaging_type="CAISSE",
                quantity=4,
                weight_kg=Decimal("95.000"),
                length_cm=Decimal("55"),
                width_cm=Decimal("45"),
                height_cm=Decimal("40"),
                declared_value=Decimal("4200.00"),
                declared_currency=currencies["USD"],
                allocated_cost_fcfa=Decimal("480000.00"),
                suggested_price_fcfa=Decimal("620000.00"),
                status="EN_TRANSIT",
                created_by=agent_user,
            )
            sync_or_create_parcel_invoice(p3, user=agent_user, create_if_missing=True)
            TrackingEvent.objects.create(
                folder=f_aer,
                parcel=p3,
                stage="DEPART",
                status_before="Ouvert",
                status_after="En transit international",
                location_text="Aéroport International de Dubaï (DXB)",
                description="Embarquement confirmé sur vol cargo ET-3915 via Addis-Abeba.",
                recorded_by=agent_user,
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Initialisation LCK Services SARL terminée avec succès !\n"
                "  • Compte administrateur d'accès : admin / LckAdmin2026!\n"
                "  • Compte agent opérationnel     : agent / LckAgent2026!"
            )
        )
