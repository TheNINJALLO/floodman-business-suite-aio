// --- ROOMFLOW COST CATALOG SYSTEM ---

const DEFAULT_CATALOG = [
    {
        id: "vapor_barrier_tape",
        name: "Vapor-Barrier Tape",
        packagePrice: 195.95,
        packageQuantity: 12,
        purchaseUnit: "case",
        usageUnit: "roll",
        taxable: true,
        defaultWaste: 10,
        active: true,
        notes: "Tape to seal vapor barrier seams. 12 rolls per case."
    },
    {
        id: "vapor_barrier",
        name: "6-Foot Vapor Barrier",
        packagePrice: 213.88,
        packageQuantity: 900, // 900 sq ft coverage per roll (150ft by 6ft)
        purchaseUnit: "roll",
        usageUnit: "square foot",
        taxable: true,
        defaultWaste: 10,
        active: true,
        notes: "150 feet by 6 feet roll. Covers 900 sq ft."
    },
    {
        id: "spray_foam",
        name: "Spray Foam",
        packagePrice: 263.99,
        packageQuantity: 24,
        purchaseUnit: "case",
        usageUnit: "can",
        taxable: true,
        defaultWaste: 10,
        active: true,
        notes: "Used for rim joist / bond pocket insulation. 24 cans per case."
    },
    {
        id: "carbon_fiber",
        name: "Carbon Fiber Reinforcement",
        packagePrice: 411.55,
        packageQuantity: 75, // 75 linear feet per roll
        purchaseUnit: "roll",
        usageUnit: "linear foot",
        taxable: true,
        defaultWaste: 10,
        active: true,
        notes: "Wall reinforcement carbon fiber strap roll (75 ft)."
    },
    {
        id: "benefect",
        name: "Benefect",
        packagePrice: 107.13,
        packageQuantity: 5, // 5 gallons per pail
        purchaseUnit: "pail",
        usageUnit: "gallon",
        taxable: true,
        defaultWaste: 10,
        active: true,
        notes: "Mold/water sanitization chemical. 5 gallons per pail."
    },
    {
        id: "rmr",
        name: "RMR Treatment",
        packagePrice: 56.39,
        packageQuantity: 2.5,
        purchaseUnit: "container",
        usageUnit: "gallon",
        taxable: true,
        defaultWaste: 10,
        active: true,
        notes: "RMR Mold removal treatment. 2.5 gallon container."
    },
    {
        id: "n95_masks",
        name: "N95 Masks",
        packagePrice: 18.57,
        packageQuantity: 1, // Will be configured in Settings (Masks per pack)
        purchaseUnit: "pack",
        usageUnit: "pack",
        taxable: true,
        defaultWaste: 0,
        active: true,
        notes: "N95 respiratory masks for crew health."
    },
    {
        id: "sump_pump_half_hp",
        name: "1/2 HP Sump Pump",
        packagePrice: 119.99,
        packageQuantity: 1,
        purchaseUnit: "each",
        usageUnit: "each",
        taxable: true,
        defaultWaste: 0,
        active: true,
        notes: "1/2 HP Submersible Sump Pump. 2 required per basin."
    },
    {
        id: "wifi_sump_float",
        name: "Wi-Fi Sump Float",
        packagePrice: 59.99,
        packageQuantity: 1,
        purchaseUnit: "each",
        usageUnit: "each",
        taxable: true,
        defaultWaste: 0,
        active: true,
        notes: "Smart Wi-Fi water level alert sensor."
    },
    {
        id: "permanent_dehumidifier",
        name: "Permanent Dehumidifier",
        packagePrice: 449.99,
        packageQuantity: 1,
        purchaseUnit: "each",
        usageUnit: "each",
        taxable: true,
        defaultWaste: 0,
        active: true,
        notes: "Permanently installed heavy duty crawlspace dehumidifier."
    },
    {
        id: "garbage_bags",
        name: "Contractor Garbage Bags",
        packagePrice: 27.56,
        packageQuantity: 50,
        purchaseUnit: "pack",
        usageUnit: "bag",
        taxable: true,
        defaultWaste: 10,
        active: true,
        notes: "50 contractor bags per box."
    },
    {
        id: "nb1",
        name: "NB-1 Coating",
        packagePrice: 80.00,
        packageQuantity: 1, // Represents 1 bag. Coverage is based on settings.
        purchaseUnit: "bag",
        usageUnit: "bag",
        taxable: true,
        defaultWaste: 10,
        active: true,
        notes: "NB-1 structural coating. Covers 8 sq ft per bag by default."
    },
    {
        id: "waterstop",
        name: "Waterstop",
        packagePrice: 130.00,
        packageQuantity: 2000, // 2000 sq ft per pail
        purchaseUnit: "pail",
        usageUnit: "square foot",
        taxable: true,
        defaultWaste: 10,
        active: true,
        notes: "2.5 gallons pail. Covers 2,000 sq ft."
    },
    {
        id: "floor_epoxy",
        name: "Floor Epoxy",
        packagePrice: 157.49,
        packageQuantity: 300, // 300 sq ft per kit
        purchaseUnit: "kit",
        usageUnit: "square foot",
        taxable: true,
        defaultWaste: 10,
        active: true,
        notes: "3 gallons floor epoxy kit. Covers 300 sq ft."
    },
    {
        id: "dehumidifier_stands",
        name: "Dehumidifier Stands",
        packagePrice: 14.99,
        packageQuantity: 4,
        purchaseUnit: "pack",
        usageUnit: "stand",
        taxable: true,
        defaultWaste: 0,
        active: true,
        notes: "Stands for dehumidifiers. 4 per pack."
    },
    {
        id: "sump_basin_drain_stone",
        name: "Sump Basin and Drain Stone Package",
        packagePrice: 250.00,
        packageQuantity: 1,
        purchaseUnit: "package",
        usageUnit: "package",
        taxable: true,
        defaultWaste: 0,
        active: true,
        notes: "Basin and aggregate stone kit for sump pit construction."
    },
    {
        id: "nb1_primer",
        name: "NB-1 Primer",
        packagePrice: 120.00,
        packageQuantity: 1,
        purchaseUnit: "bucket",
        usageUnit: "bucket",
        taxable: true,
        defaultWaste: 10,
        active: true,
        notes: "NB-1 Primer (2.5 gallon). Covers roughly 30 bags of NB-1 worth of area."
    },
    {
        id: "drywall_cut",
        name: "Drywall Cutting",
        packagePrice: 1.98,
        packageQuantity: 1,
        purchaseUnit: "sq ft",
        usageUnit: "square foot",
        taxable: false,
        defaultWaste: 0,
        active: true,
        notes: "Cutting drywall at specified height. Charged per sq ft."
    },
    {
        id: "insulation_removal",
        name: "Attic Insulation Removal",
        packagePrice: 1.75,
        packageQuantity: 1,
        purchaseUnit: "sq ft",
        usageUnit: "square foot",
        taxable: false,
        defaultWaste: 0,
        active: true,
        notes: "Attic insulation removal. Charged per sq ft."
    },
    {
        id: "insulation_blowing",
        name: "Blown-in Attic Insulation",
        packagePrice: 2.25,
        packageQuantity: 1,
        purchaseUnit: "sq ft",
        usageUnit: "square foot",
        taxable: false,
        defaultWaste: 0,
        active: true,
        notes: "Blowing back in new cellulose or fiberglass attic insulation. Charged per sq ft."
    }
];

const RoomFlowCatalog = {
    getDefaults: function() {
        return JSON.parse(JSON.stringify(DEFAULT_CATALOG));
    },

    loadCatalog: function() {
        try {
            const stored = localStorage.getItem('roomflow_cost_catalog_v1');
            if (stored) {
                const parsed = JSON.parse(stored);
                // Validate and merge missing default items
                const validList = [];
                const parsedMap = new Map(parsed.map(item => [item.id, item]));
                
                DEFAULT_CATALOG.forEach(defaultItem => {
                    if (parsedMap.has(defaultItem.id)) {
                        const storedItem = parsedMap.get(defaultItem.id);
                        // Clean up potential invalid fields
                        const merged = { ...defaultItem, ...storedItem };
                        merged.packagePrice = Math.max(0, parseFloat(merged.packagePrice) || 0);
                        merged.packageQuantity = Math.max(0.001, parseFloat(merged.packageQuantity) || 1);
                        merged.defaultWaste = Math.max(0, parseFloat(merged.defaultWaste) || 0);
                        validList.push(merged);
                    } else {
                        validList.push(JSON.parse(JSON.stringify(defaultItem)));
                    }
                });
                return validList;
            }
        } catch (e) {
            console.error("Failed to load catalog from localStorage, falling back to defaults:", e);
        }
        return this.getDefaults();
    },

    saveCatalog: function(catalogList) {
        if (!this.validateCatalog(catalogList)) {
            throw new Error("Invalid catalog data. Cannot save.");
        }
        localStorage.setItem('roomflow_cost_catalog_v1', JSON.stringify(catalogList));
    },

    resetToDefaults: function() {
        localStorage.removeItem('roomflow_cost_catalog_v1');
        return this.getDefaults();
    },

    validateCatalog: function(catalogList) {
        if (!Array.isArray(catalogList)) return false;
        const ids = new Set();
        for (let i = 0; i < catalogList.length; i++) {
            const item = catalogList[i];
            if (!item.id || typeof item.id !== "string" || item.id.trim() === "") {
                console.warn("Validation failed: missing or empty ID", item);
                return false;
            }
            if (ids.has(item.id)) {
                console.warn("Validation failed: duplicate ID " + item.id);
                return false;
            }
            ids.add(item.id);
            if (!item.name || typeof item.name !== "string" || item.name.trim() === "") {
                console.warn("Validation failed: missing product name", item);
                return false;
            }
            if (typeof item.packagePrice !== "number" || item.packagePrice < 0 || isNaN(item.packagePrice)) {
                console.warn("Validation failed: invalid packagePrice", item);
                return false;
            }
            if (typeof item.packageQuantity !== "number" || item.packageQuantity <= 0 || isNaN(item.packageQuantity)) {
                console.warn("Validation failed: invalid packageQuantity", item);
                return false;
            }
            if (typeof item.defaultWaste !== "number" || item.defaultWaste < 0 || isNaN(item.defaultWaste)) {
                console.warn("Validation failed: invalid defaultWaste", item);
                return false;
            }
        }
        return true;
    },

    exportJSON: function(catalogList) {
        return JSON.stringify(catalogList, null, 2);
    },

    importJSON: function(jsonString) {
        try {
            const parsed = JSON.parse(jsonString);
            if (this.validateCatalog(parsed)) {
                return parsed;
            } else {
                throw new Error("JSON failed catalog schema validation rules.");
            }
        } catch (e) {
            throw new Error("Failed to parse or validate catalog JSON: " + e.message);
        }
    }
};

// Bind to window context
window.RoomFlowCatalog = RoomFlowCatalog;
window.DEFAULT_CATALOG = DEFAULT_CATALOG;
