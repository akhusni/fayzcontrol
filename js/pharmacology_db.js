/**
 * Fayz Medical House - Clinical Pharmacology Database & Search API
 * Jurisdiction: Republic of Uzbekistan (State Register of Medicines)
 * Total Medications: 206+ Clinical Records
 * Version: 3.5.0-ENTERPRISE
 */

const PHARMACOLOGY_DATABASE_URI = './data/pharmacology_db.json';

class PharmacologyEngine {
    constructor() {
        this.data = null;
        this.medications = [];
        this.categories = [];
        this.isLoaded = false;
        this.loadPromise = this.init();
    }

    async init() {
        try {
            const response = await fetch(PHARMACOLOGY_DATABASE_URI);
            if (!response.ok) {
                throw new Error(`Failed to load pharmacology database: ${response.statusText}`);
            }
            this.data = await response.json();
            this.medications = this.data.medications || [];
            this.categories = this.data.categories || [];
            this.isLoaded = true;
            console.log(`[PharmacologyEngine] Loaded ${this.medications.length} drugs across ${this.categories.length} categories.`);
            return this.data;
        } catch (error) {
            console.error('[PharmacologyEngine] Initialization error:', error);
            return null;
        }
    }

    async ready() {
        if (this.isLoaded) return this.data;
        return await this.loadPromise;
    }

    /**
     * Search medications by trade name, INN, ATC code, manufacturer, or indication
     * @param {string} query Search keyword
     * @param {string} [category] Optional category filter
     * @param {string} [prescriptionType] Optional prescription type filter (OTC, Rx_Standard, Rx_Strict_Psychotropic)
     * @param {string} [lang] Language ('uz', 'ru', 'en')
     */
    search(query = '', category = 'all', prescriptionType = 'all', lang = 'uz') {
        const q = query.trim().toLowerCase();
        
        return this.medications.filter(med => {
            // Category filter
            if (category && category !== 'all' && med.category !== category) {
                return false;
            }

            // Prescription type filter
            if (prescriptionType && prescriptionType !== 'all' && med.prescription_type !== prescriptionType) {
                return false;
            }

            if (!q) return true;

            const nameMatch = (med.name || '').toLowerCase().includes(q) ||
                              (med.paper_name || '').toLowerCase().includes(q);

            const tradeMatch = (med.trade_name || '').toLowerCase().includes(q) ||
                               (med.trade_name_uz || '').toLowerCase().includes(q) ||
                               (med.trade_name_ru || '').toLowerCase().includes(q) ||
                               (med.trade_name_en || '').toLowerCase().includes(q);

            const innMatch = (med.inn || '').toLowerCase().includes(q) ||
                             (med.inn_uz || '').toLowerCase().includes(q) ||
                             (med.inn_ru || '').toLowerCase().includes(q) ||
                             (med.inn_en || '').toLowerCase().includes(q);

            const atcMatch = (med.atc_code || '').toLowerCase().includes(q);
            const mfgMatch = (med.manufacturer || '').toLowerCase().includes(q) ||
                             (med.country || '').toLowerCase().includes(q);

            const indMatch = med.indications && (
                (med.indications.uz || '').toLowerCase().includes(q) ||
                (med.indications.ru || '').toLowerCase().includes(q) ||
                (med.indications.en || '').toLowerCase().includes(q)
            );

            const pharmGroupMatch = med.pharmacological_group && (
                (med.pharmacological_group.uz || '').toLowerCase().includes(q) ||
                (med.pharmacological_group.ru || '').toLowerCase().includes(q) ||
                (med.pharmacological_group.en || '').toLowerCase().includes(q)
            );

            return nameMatch || tradeMatch || innMatch || atcMatch || mfgMatch || indMatch || pharmGroupMatch;
        });
    }

    /**
     * Get single medication by ID
     * @param {string} id Unique medication ID (e.g. 'NARC-001')
     */
    getById(id) {
        return this.medications.find(m => m.id === id) || null;
    }

    /**
     * Get medications by clinical category
     * @param {string} category Category ID (e.g. 'narcology_detox', 'psychiatry_antidepressants')
     */
    getByCategory(category) {
        return this.medications.filter(m => m.category === category);
    }

    /**
     * Get the official Fayz Medical House 88 clinic formulary medications
     */
    getClinicFormulary() {
        return this.medications
            .filter(m => m.fayz_house_list === true)
            .sort((a, b) => (a.fayz_house_num || 0) - (b.fayz_house_num || 0));
    }

    /**
     * Analyze multiple drug IDs for safety interactions and contraindications
     * @param {string[]} drugIds List of medication IDs selected in patient recipe
     */
    checkInteractions(drugIds) {
        const selectedMeds = drugIds.map(id => this.getById(id)).filter(Boolean);
        const warnings = [];

        for (let i = 0; i < selectedMeds.length; i++) {
            for (let j = i + 1; j < selectedMeds.length; j++) {
                const medA = selectedMeds[i];
                const medB = selectedMeds[j];

                // Check SSRI + MAOI
                const isSSRI = medA.category === 'psychiatry_antidepressants' && medA.pharmacological_group.en.toLowerCase().includes('ssri');
                const isMAOI = medB.inn.toLowerCase().includes('moclobemide') || medB.trade_name.toLowerCase().includes('aurorix');
                if (isSSRI && isMAOI) {
                    warnings.push({
                        severity: 'CRITICAL',
                        title: 'Serotonin Sindromi Xavfi (SSRI + MAOI)',
                        description: `${medA.trade_name} va ${medB.trade_name} birgalikda qo'llanilganda o'limga olib keluvchi gipertermiya va serotoninergik inqiroz chaqirishi mumkin!`
                    });
                }

                // Check Disulfiram + Alcohol-containing syrups
                if (medA.inn.toLowerCase().includes('disulfiram') && medB.dosage_form.toLowerCase().includes('solution') && medB.trade_name.toLowerCase().includes('novo-passit')) {
                    warnings.push({
                        severity: 'HIGH',
                        title: 'Disulfiram Reaksiyasi (Spirt saqlovchi fitopreparat)',
                        description: `${medA.trade_name} bilan ${medB.trade_name} (spirtli damlama) birga berilsa aversiv toksik kollaps yuzaga keladi.`
                    });
                }

                // Check Benzodiazepine + Opioid
                const isBenzo = medA.category === 'psychiatry_anxiolytics_hypnotics' && medA.prescription_type === 'Rx_Strict_Psychotropic';
                const isOpioid = medB.inn.toLowerCase().includes('tramadol');
                if (isBenzo && isOpioid) {
                    warnings.push({
                        severity: 'HIGH',
                        title: 'Nafas Markazi Tormozlanishi (Benzodiazepin + Opioid)',
                        description: `${medA.trade_name} va ${medB.trade_name} markaziy asab tizimi va nafas markazini kuchli susaytiradi. Dozani qat'iy nazorat qiling.`
                    });
                }
            }
        }

        return {
            safe: warnings.length === 0,
            warnings: warnings,
            analyzedCount: selectedMeds.length
        };
    }
}

// Global instance for HIS modules
window.PharmacologyDB = new PharmacologyEngine();
