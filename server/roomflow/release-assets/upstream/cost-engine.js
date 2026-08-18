// --- ROOMFLOW COSTING ENGINE & CALCULATIONS ---

// Global Settings default values
const DEFAULT_COST_SETTINGS = {
    taxRate: 6.0,          // Michigan sales/use tax
    generalWaste: 10.0,    // General material waste %
    overhead: 15.0,        // Overhead %
    markup: 30.0,          // Markup %
    loadedLaborRate: 45.0,  // Loaded labor rate ($/hour)
    hoursPerWorkday: 8,    // Workday duration

    // Catalog coverage / configurations
    tapeCoveragePerRoll: 250,     // 1 roll covers 250 ft of seams and corners by default
    benefectSqFtPerGallon: 1000,  // 1 pail (5 gal) covers 5000 sq ft by default
    rmrSqFtPerGallon: 2000,       // 1 container (2.5 gal) covers 5000 sq ft by default
    masksPerPack: 0,            // 0 means unconfigured
    nb1SqFtPerBag: 8,           // default legacy is 8 sq ft per bag

    // Masks Mode: 'manual' or 'crew'
    masksMode: 'manual',
    crewSize: 1,
    workdays: 1,
    masksPerWorkerPerDay: 1,

    // Pricing Mode: 'markup' or 'target-margin'
    pricingMode: 'markup',
    targetGrossMargin: 40.0, // Target gross margin %
    useVaporBarrier: true
};

// Initialize costing state with defaults
function initDefaultCosting(projState) {
    if (!projState.costing) {
        projState.costing = {
            version: "1.0",
            settings: JSON.parse(JSON.stringify(DEFAULT_COST_SETTINGS)),
            catalogOverrides: {},
            projectOverrides: {},
            labor: {
                mode: 'project', // 'project' or 'detailed' or 'combined'
                projectCrewSize: 1,
                projectWorkdays: 1,
                projectHoursPerDay: 8,
                projectLaborRate: 120,
                projectNotes: '',
                detailedLines: []
            },
            rentals: {
                dehumidifierUnits: 0,
                dehumidifierDays: 0,
                dehumidifierTaxable: true,
                dehumidifierNotes: '',
                airMoverUnits: 0,
                airMoverDays: 0,
                airMoverTaxable: true,
                airMoverNotes: '',
                airScrubberUnits: 0,
                airScrubberDays: 0,
                airScrubberTaxable: true,
                airScrubberNotes: '',
                optionalCharges: []
            },
            customItems: [],
            treatmentSelections: {},
            manualQuantityOverrides: {},
            excludedItems: {},
            documents: {
                proposalNumber: '',
                invoiceNumber: '',
                invoiceStatus: 'Draft',
                dueDate: '',
                paymentTerms: 'Due within 30 days',
                depositPaid: 0,
                notes: '',
                includeCustomerInfo: true,
                includeBlueprint: true,
                showItemizedPricing: true,
                includeTotalPricing: true,
                itemVisibility: {}
            }
        };
    } else {
        // Migration and merging for backward compatibility
        const costing = projState.costing;
        if (!costing.settings) costing.settings = {};
        
        // Merge settings defaults
        Object.keys(DEFAULT_COST_SETTINGS).forEach(k => {
            if (costing.settings[k] === undefined) {
                costing.settings[k] = DEFAULT_COST_SETTINGS[k];
            }
        });
        
        if (!costing.catalogOverrides) costing.catalogOverrides = {};
        if (!costing.projectOverrides) costing.projectOverrides = {};
        if (!costing.labor) {
            costing.labor = {
                mode: 'project',
                projectCrewSize: 1,
                projectWorkdays: 1,
                projectHoursPerDay: 8,
                projectLaborRate: 65,
                projectNotes: '',
                detailedLines: []
            };
        }
        if (!costing.rentals) {
            costing.rentals = {
                dehumidifierUnits: 0,
                dehumidifierDays: 0,
                dehumidifierTaxable: true,
                dehumidifierNotes: '',
                airMoverUnits: 0,
                airMoverDays: 0,
                airMoverTaxable: true,
                airMoverNotes: '',
                airScrubberUnits: 0,
                airScrubberDays: 0,
                airScrubberTaxable: true,
                airScrubberNotes: '',
                optionalCharges: []
            };
        } else {
            if (costing.rentals.airScrubberUnits === undefined) costing.rentals.airScrubberUnits = 0;
            if (costing.rentals.airScrubberDays === undefined) costing.rentals.airScrubberDays = 0;
            if (costing.rentals.airScrubberTaxable === undefined) costing.rentals.airScrubberTaxable = true;
            if (costing.rentals.airScrubberNotes === undefined) costing.rentals.airScrubberNotes = '';
        }
        if (!costing.customItems) costing.customItems = [];
        if (!costing.treatmentSelections) costing.treatmentSelections = {};
        if (!costing.manualQuantityOverrides) costing.manualQuantityOverrides = {};
        if (!costing.excludedItems) costing.excludedItems = {};
        if (!costing.documents) costing.documents = {};
        const documentDefaults = {
            proposalNumber: '',
            invoiceNumber: '',
            invoiceStatus: 'Draft',
            dueDate: '',
            paymentTerms: 'Due within 30 days',
            depositPaid: 0,
            notes: '',
            includeCustomerInfo: true,
            includeBlueprint: true,
            showItemizedPricing: true,
            includeTotalPricing: true,
            itemVisibility: {}
        };
        Object.keys(documentDefaults).forEach(k => {
            if (costing.documents[k] === undefined) costing.documents[k] = documentDefaults[k];
        });
        if (!costing.version) costing.version = "1.0";
    }
}

// Helper: safe currency formatting
function formatCurrency(value) {
    if (value === undefined || value === null || isNaN(value) || !isFinite(value)) {
        return "$0.00";
    }
    return "$" + value.toFixed(2).replace(/\d(?=(\d{3})+\.)/g, '$&,');
}

// Centralized calculation of quantities based on blueprint geometry
function calculateProjectQuantities(projState) {
    const q = {
        totalRooms: projState.rooms.length,
        totalFloorArea: 0,
        totalWallArea: 0,
        totalCeilingArea: 0,
        totalVolume: 0,
        totalPerimeter: 0,
        
        // Material quantities
        totalXpsSheets: 0,
        totalLinerArea: 0,
        totalCarbonFiberLen: 0,
        totalNb1Area: 0,
        totalDrywallCutArea: 0,
        totalInsulationRemoveArea: 0,
        totalInsulationBlowArea: 0,
        totalSprayFoamCans: 0,
        
        // Treatments (Waterstop, Floor Epoxy, Mold)
        totalWaterstopArea: 0,
        totalEpoxyArea: 0,
        totalMoldArea: 0
    };

    projState.rooms.forEach(room => {
        let floorArea, perimeter;
        if (room.type === 'custom' && room.vertices && room.vertices.length >= 3) {
            floorArea = getPolygonArea(room.vertices);
            perimeter = getPolygonPerimeter(room.vertices);
        } else {
            floorArea = room.w * room.l;
            perimeter = 2 * (room.w + room.l);
        }
        q.totalFloorArea += floorArea;
        q.totalCeilingArea += floorArea;
        q.totalPerimeter += perimeter;

        const volume = room.type === 'staircase' ? 0.5 * floorArea * room.h : floorArea * room.h;
        q.totalVolume += volume;

        let grossWallArea;
        if (room.type === 'staircase') {
            grossWallArea = (room.l * room.h) + (room.w * room.h);
        } else {
            grossWallArea = perimeter * room.h;
        }
        let deductions = 0;
        room.openings.forEach(op => { deductions += op.w * op.h; });
        const netWallArea = Math.max(0, grossWallArea - deductions);
        q.totalWallArea += netWallArea;

        // XPS Foam Sheets
        if (room.foamBoard) {
            const extPerim = getRoomExteriorPerimeter(room);
            let sheets = 0;
            if (room.h <= 4) {
                sheets = extPerim / 8;
            } else {
                const columns = extPerim / 4;
                const sheetsPerColumn = Math.ceil(room.h / 8);
                sheets = columns * sheetsPerColumn;
            }
            let xpsDeductions = 0;
            room.openings.forEach(op => { xpsDeductions += (op.w * op.h) / 32; });
            q.totalXpsSheets += Math.max(0, sheets - xpsDeductions);
        }

        // Liner Area
        q.totalLinerArea += floorArea + netWallArea;

        // Carbon Fiber
        if (room.carbonStraps > 0) {
            q.totalCarbonFiberLen += room.carbonStraps * room.h;
        }
        if (room.floorPerimeterStrap) {
            q.totalCarbonFiberLen += perimeter;
        }

        // NB1 Area
        if (room.nb1Height === '2ft') {
            q.totalNb1Area += perimeter * 2;
        } else if (room.nb1Height === '4ft') {
            q.totalNb1Area += perimeter * 4;
        } else if (room.nb1Height === 'full') {
            q.totalNb1Area += netWallArea;
        }

        // Drywall Cut Area. When drywallWalls is present, only selected wall
        // segments are included. Older projects without this field retain the
        // original full-perimeter behavior.
        if (room.drywallHeight && room.drywallHeight !== 'none') {
            const allSegments = typeof getRoomSegments === 'function' ? getRoomSegments(room) : [];
            const scopedSegments = Array.isArray(room.drywallWalls)
                ? allSegments.filter(seg => room.drywallWalls.includes(String(seg.wall)))
                : allSegments;
            const scopedPerimeter = scopedSegments.reduce((sum, seg) => {
                return sum + Math.hypot(seg.x2 - seg.x1, seg.y2 - seg.y1);
            }, allSegments.length ? 0 : perimeter);
            const heightMap = { '1ft': 1, '2ft': 2, '4ft': 4, '6ft': 6 };

            if (room.drywallHeight === 'full') {
                let scopedArea = scopedPerimeter * room.h;
                (room.openings || []).forEach(op => {
                    const wallIsIncluded = !Array.isArray(room.drywallWalls) || room.drywallWalls.includes(String(op.wall));
                    if (wallIsIncluded) scopedArea -= (op.w || 0) * (op.h || 0);
                });
                q.totalDrywallCutArea += Math.max(0, scopedArea);
            } else if (heightMap[room.drywallHeight]) {
                q.totalDrywallCutArea += scopedPerimeter * heightMap[room.drywallHeight];
            }
        }

        // Attic Insulation
        if (room.removeInsulation) {
            q.totalInsulationRemoveArea += floorArea;
        }
        if (room.blowInInsulation) {
            q.totalInsulationBlowArea += floorArea;
        }

        // Spray Foam cans
        if (room.foamBondPockets && room.joists && room.joists !== 'none') {
            const segments = getRoomSegments(room);
            let wallLen = 0;
            segments.forEach(seg => {
                const dx = seg.x2 - seg.x1;
                const dy = seg.y2 - seg.y1;
                if (room.joists === 'ns') {
                    wallLen += Math.abs(dx);
                } else if (room.joists === 'ew') {
                    wallLen += Math.abs(dy);
                }
            });
            const roomBF = wallLen * 1.5;
            q.totalSprayFoamCans += Math.ceil(roomBF / 20);
        }

        // Selections for Waterstop, Epoxy, and Mold Treatments
        if (projState.costing && projState.costing.treatmentSelections && projState.costing.treatmentSelections[room.id]) {
            const ts = projState.costing.treatmentSelections[room.id];
            
            // Waterstop
            if (ts.waterstop === 'floor') {
                q.totalWaterstopArea += floorArea;
            } else if (ts.waterstop === 'walls') {
                q.totalWaterstopArea += netWallArea;
            } else if (ts.waterstop === 'both') {
                q.totalWaterstopArea += floorArea + netWallArea;
            } else if (ts.waterstop === 'custom') {
                q.totalWaterstopArea += Math.max(0, parseFloat(ts.waterstopCustomArea) || 0);
            }

            // Epoxy
            if (ts.epoxy === 'entire') {
                q.totalEpoxyArea += floorArea;
            } else if (ts.epoxy === 'custom') {
                q.totalEpoxyArea += Math.max(0, parseFloat(ts.epoxyCustomArea) || 0);
            }

            // Mold
            q.totalMoldArea += Math.max(0, parseFloat(ts.moldArea) || 0);
        }
    });

    // Stanchions (columns) liner area
    projState.stanchions.forEach(st => {
        const stLevelId = st.levelId || 'basement';
        const level = projState.levels.find(l => l.id === stLevelId) || { height: 8 };
        const room = getRoomAt(st.x, st.y, stLevelId);
        const roomH = room ? room.h : (level.height || 8);

        let isUnderBeam = false;
        const bHeight = 0.9;
        for (let i = 0; i < projState.mainBeams.length; i++) {
            const bm = projState.mainBeams[i];
            if (bm.levelId !== stLevelId) continue;
            const dist = getDistanceToSegment(st.x, st.y, bm.x1, bm.y1, bm.x2, bm.y2);
            if (dist < 0.5) {
                isUnderBeam = true;
                break;
            }
        }
        const postH = isUnderBeam ? Math.max(0.5, roomH - bHeight) : roomH;

        let perim = 0;
        if (st.type === 'round') {
            perim = 2 * Math.PI * 0.4;
        } else if (st.type === 'square') {
            perim = 4 * 0.8;
        } else if (st.type === 'brick') {
            perim = 4 * 1.0;
        }
        q.totalLinerArea += perim * postH;
    });

    // Estimate PVC sticks & Sump installation plumbing BOM
    q.plumbingEst = estimatePlumbingMaterials();

    return q;
}

// Perform cost estimates
function calculateProjectCosts(projState, catalogList) {
    const q = calculateProjectQuantities(projState);
    const costing = projState.costing;
    const settings = costing.settings;

    // Map catalog list for easy access
    const catalogMap = new Map(catalogList.map(item => [item.id, item]));

    // Helper to get item price, waste, active state, and overrides
    function getItemData(id) {
        const item = catalogMap.get(id);
        const override = costing.catalogOverrides[id] || {};
        return {
            id: id,
            name: override.name || item.name,
            packagePrice: Math.max(0, override.packagePrice !== undefined ? override.packagePrice : item.packagePrice),
            packageQuantity: Math.max(0.001, override.packageQuantity !== undefined ? override.packageQuantity : item.packageQuantity),
            purchaseUnit: override.purchaseUnit || item.purchaseUnit,
            usageUnit: override.usageUnit || item.usageUnit,
            taxable: override.taxable !== undefined ? override.taxable : item.taxable,
            defaultWaste: Math.max(0, override.defaultWaste !== undefined ? override.defaultWaste : item.defaultWaste),
            active: override.active !== undefined ? override.active : item.active,
            notes: override.notes || item.notes
        };
    }

    // Helper: apply manual override or auto-calculated value
    function getQuantity(id, calculatedQty) {
        const ovr = costing.manualQuantityOverrides[id];
        if (ovr && ovr.overrideEnabled) {
            return {
                quantity: Math.max(0, parseFloat(ovr.overrideQuantity) || 0),
                overrideEnabled: true
            };
        }
        return {
            quantity: Math.max(0, calculatedQty),
            overrideEnabled: false
        };
    }

    const report = {
        items: {},
        warnings: {},
        subtotals: {
            material: 0,
            equipment: 0,
            supply: 0,
            rental: 0,
            taxable: 0,
            tax: 0,
            labor: 0,
            custom: 0,
            direct: 0,
            overhead: 0,
            costBasis: 0,
            markup: 0,
            sellingPrice: 0,
            grossProfit: 0,
            marginPercent: 0
        }
    };

    // 1. Vapor-Barrier Tape
    const tapeItem = getItemData('vapor_barrier_tape');
    let tapeRollsCalc = 0;
    if (settings.tapeCoveragePerRoll > 0) {
        tapeRollsCalc = q.totalLinerArea / settings.tapeCoveragePerRoll;
    } else {
        report.warnings['vapor_barrier_tape'] = "Tape Coverage Missing: Set 'Coverage per roll' in settings or enter rolls manually.";
    }
    const tapeRollsData = getQuantity('vapor_barrier_tape', tapeRollsCalc);
    const tapeCases = Math.ceil(tapeRollsData.quantity / 12);
    const tapeCost = tapeCases * tapeItem.packagePrice;
    report.items['vapor_barrier_tape'] = {
        data: tapeItem,
        measured: tapeRollsCalc,
        adjusted: tapeRollsData.quantity,
        purchaseQty: tapeCases,
        cost: tapeCost,
        overrideEnabled: tapeRollsData.overrideEnabled,
        extraRemaining: (tapeCases * 12) - tapeRollsData.quantity
    };

    // 2. Vapor Barrier
    const vbItem = getItemData('vapor_barrier');
    const vbWasteMultiplier = 1 + (settings.generalWaste / 100);
    const vbCoverageCalc = q.totalLinerArea * vbWasteMultiplier;
    const vbRollsCalc = Math.ceil(vbCoverageCalc / vbItem.packageQuantity);
    const vbRollsData = getQuantity('vapor_barrier', vbRollsCalc);
    const vbCost = vbRollsData.quantity * vbItem.packagePrice;
    report.items['vapor_barrier'] = {
        data: vbItem,
        measured: q.totalLinerArea,
        adjusted: vbCoverageCalc,
        purchaseQty: vbRollsData.quantity,
        cost: vbCost,
        overrideEnabled: vbRollsData.overrideEnabled,
        extraRemaining: (vbRollsData.quantity * vbItem.packageQuantity) - vbCoverageCalc
    };

    // 3. Spray Foam
    const foamItem = getItemData('spray_foam');
    const foamCasesCalc = Math.ceil(q.totalSprayFoamCans / 24);
    const foamCasesData = getQuantity('spray_foam', foamCasesCalc);
    const foamCost = foamCasesData.quantity * foamItem.packagePrice;
    report.items['spray_foam'] = {
        data: foamItem,
        measured: q.totalSprayFoamCans,
        adjusted: q.totalSprayFoamCans,
        purchaseQty: foamCasesData.quantity,
        cost: foamCost,
        overrideEnabled: foamCasesData.overrideEnabled,
        extraRemaining: (foamCasesData.quantity * 24) - q.totalSprayFoamCans
    };

    // 4. Carbon Fiber
    const cfItem = getItemData('carbon_fiber');
    const cfWasteMultiplier = 1 + (settings.generalWaste / 100);
    const cfLenCalc = q.totalCarbonFiberLen * cfWasteMultiplier;
    const cfRollsCalc = Math.ceil(cfLenCalc / 75);
    const cfRollsData = getQuantity('carbon_fiber', cfRollsCalc);
    const cfCost = cfRollsData.quantity * cfItem.packagePrice;
    report.items['carbon_fiber'] = {
        data: cfItem,
        measured: q.totalCarbonFiberLen,
        adjusted: cfLenCalc,
        purchaseQty: cfRollsData.quantity,
        cost: cfCost,
        overrideEnabled: cfRollsData.overrideEnabled,
        extraRemaining: (cfRollsData.quantity * 75) - cfLenCalc
    };

    // 5. Benefect
    const benefectItem = getItemData('benefect');
    let benefectGallonsCalc = 0;
    let benefectPailsCalc = 0;
    if (q.totalMoldArea > 0) {
        if (settings.benefectSqFtPerGallon > 0) {
            benefectGallonsCalc = q.totalMoldArea / settings.benefectSqFtPerGallon;
            benefectPailsCalc = Math.ceil(benefectGallonsCalc / 5);
        } else {
            report.warnings['benefect'] = "Benefect Coverage Missing: Set 'Square feet per gallon' in settings or enter quantity manually.";
        }
    }
    const benefectPailsData = getQuantity('benefect', benefectPailsCalc);
    const benefectCost = benefectPailsData.quantity * benefectItem.packagePrice;
    report.items['benefect'] = {
        data: benefectItem,
        measured: q.totalMoldArea,
        adjusted: benefectGallonsCalc,
        purchaseQty: benefectPailsData.quantity,
        cost: benefectCost,
        overrideEnabled: benefectPailsData.overrideEnabled,
        extraRemaining: (benefectPailsData.quantity * 5) - benefectGallonsCalc
    };

    // 6. RMR
    const rmrItem = getItemData('rmr');
    let rmrGallonsCalc = 0;
    let rmrPacksCalc = 0;
    if (q.totalMoldArea > 0) {
        if (settings.rmrSqFtPerGallon > 0) {
            rmrGallonsCalc = q.totalMoldArea / settings.rmrSqFtPerGallon;
            rmrPacksCalc = Math.ceil(rmrGallonsCalc / 1.5);
        } else {
            report.warnings['rmr'] = "RMR Coverage Missing: Set 'Square feet per gallon' in settings or enter quantity manually.";
        }
    }
    const rmrPacksData = getQuantity('rmr', rmrPacksCalc);
    const rmrCost = rmrPacksData.quantity * rmrItem.packagePrice;
    report.items['rmr'] = {
        data: rmrItem,
        measured: q.totalMoldArea,
        adjusted: rmrGallonsCalc,
        purchaseQty: rmrPacksData.quantity,
        cost: rmrCost,
        overrideEnabled: rmrPacksData.overrideEnabled,
        extraRemaining: (rmrPacksData.quantity * 1.5) - rmrGallonsCalc
    };

    // Determine Crew/Workdays details from settings or labor
    let crewSize = settings.crewSize;
    let workdays = settings.workdays;
    if (costing.labor.mode === 'project') {
        crewSize = costing.labor.projectCrewSize || settings.crewSize;
        workdays = costing.labor.projectWorkdays || settings.workdays;
    }

    // 7. N95 Masks
    const masksItem = getItemData('n95_masks');
    let masksPacksCalc = 0;
    let totalMasksReq = 0;
    if (settings.masksPerPack > 0) {
        if (settings.masksMode === 'crew') {
            totalMasksReq = crewSize * workdays * settings.masksPerWorkerPerDay;
            masksPacksCalc = Math.ceil(totalMasksReq / settings.masksPerPack);
        }
    } else {
        report.warnings['n95_masks'] = "Masks per pack not configured. Please enter mask settings.";
    }
    const masksPacksData = getQuantity('n95_masks', masksPacksCalc);
    const masksCost = masksPacksData.quantity * masksItem.packagePrice;
    report.items['n95_masks'] = {
        data: masksItem,
        measured: totalMasksReq,
        adjusted: totalMasksReq,
        purchaseQty: masksPacksData.quantity,
        cost: masksCost,
        overrideEnabled: masksPacksData.overrideEnabled,
        extraRemaining: (settings.masksPerPack > 0) ? (masksPacksData.quantity * settings.masksPerPack) - totalMasksReq : 0
    };

    // 8. 1/2 HP Sump Pump
    const pumpItem = getItemData('sump_pump_half_hp');
    // Calculate total pumps using default 2 per basin, or basin overrides
    let totalPumpsCalc = 0;
    projState.sumpPumps.forEach(sp => {
        let pumpsCount = settings.sumpPumpsPerBasin || 2;
        if (costing.projectOverrides && costing.projectOverrides[sp.id] && costing.projectOverrides[sp.id].pumps !== undefined) {
            pumpsCount = Math.max(0, parseInt(costing.projectOverrides[sp.id].pumps) || 0);
        }
        totalPumpsCalc += pumpsCount;
    });
    const pumpData = getQuantity('sump_pump_half_hp', totalPumpsCalc);
    const pumpCost = pumpData.quantity * pumpItem.packagePrice;
    report.items['sump_pump_half_hp'] = {
        data: pumpItem,
        measured: totalPumpsCalc,
        adjusted: totalPumpsCalc,
        purchaseQty: pumpData.quantity,
        cost: pumpCost,
        overrideEnabled: pumpData.overrideEnabled,
        extraRemaining: 0
    };

    // 9. Wi-Fi Sump Float
    const floatItem = getItemData('wifi_sump_float');
    // Float defaults to pump quantity
    const floatData = getQuantity('wifi_sump_float', pumpData.quantity);
    const floatCost = floatData.quantity * floatItem.packagePrice;
    report.items['wifi_sump_float'] = {
        data: floatItem,
        measured: pumpData.quantity,
        adjusted: pumpData.quantity,
        purchaseQty: floatData.quantity,
        cost: floatCost,
        overrideEnabled: floatData.overrideEnabled,
        extraRemaining: 0
    };

    // Calculate permanent dehumidifiers from placed elements and settings/overrides
    let totalPlacedDehums = (projState.dehumidifiers || []).length;
    let permDehumCalc = totalPlacedDehums;
    if (costing.projectOverrides && costing.projectOverrides.permanentDehumQty !== undefined) {
        permDehumCalc = Math.max(0, parseInt(costing.projectOverrides.permanentDehumQty) || 0);
    }

    // 10. Permanent Dehumidifier
    const pdItem = getItemData('permanent_dehumidifier');
    const pdData = getQuantity('permanent_dehumidifier', permDehumCalc);
    const pdCost = pdData.quantity * pdItem.packagePrice;
    report.items['permanent_dehumidifier'] = {
        data: pdItem,
        measured: permDehumCalc,
        adjusted: permDehumCalc,
        purchaseQty: pdData.quantity,
        cost: pdCost,
        overrideEnabled: pdData.overrideEnabled,
        extraRemaining: 0
    };

    // 11. Contractor Garbage Bags
    const bagsItem = getItemData('garbage_bags');
    let bagsCalc = 0;
    if (costing.projectOverrides && costing.projectOverrides.garbageBagsQty !== undefined) {
        bagsCalc = Math.max(0, parseInt(costing.projectOverrides.garbageBagsQty) || 0);
    }
    const bagsPacksCalc = Math.ceil(bagsCalc / 50);
    const bagsPacksData = getQuantity('garbage_bags', bagsPacksCalc);
    const bagsCost = bagsPacksData.quantity * bagsItem.packagePrice;
    report.items['garbage_bags'] = {
        data: bagsItem,
        measured: bagsCalc,
        adjusted: bagsCalc,
        purchaseQty: bagsPacksData.quantity,
        cost: bagsCost,
        overrideEnabled: bagsPacksData.overrideEnabled,
        extraRemaining: (bagsPacksData.quantity * 50) - bagsCalc
    };

    // 12. NB-1 Coating
    const nb1Item = getItemData('nb1');
    const nb1CoveragePerBag = settings.nb1SqFtPerBag || 8;
    const nb1BagsCalc = Math.ceil(q.totalNb1Area / nb1CoveragePerBag);
    const nb1BagsData = getQuantity('nb1', nb1BagsCalc);
    const nb1Cost = nb1BagsData.quantity * nb1Item.packagePrice;
    report.items['nb1'] = {
        data: nb1Item,
        measured: q.totalNb1Area,
        adjusted: q.totalNb1Area,
        purchaseQty: nb1BagsData.quantity,
        cost: nb1Cost,
        overrideEnabled: nb1BagsData.overrideEnabled,
        extraRemaining: 0
    };

    // 12b. NB-1 Primer
    const primerItem = getItemData('nb1_primer');
    const primerBucketsCalc = Math.ceil(nb1BagsData.quantity / 30);
    const primerBucketsData = getQuantity('nb1_primer', primerBucketsCalc);
    const primerCost = primerBucketsData.quantity * primerItem.packagePrice;
    report.items['nb1_primer'] = {
        data: primerItem,
        measured: nb1BagsData.quantity,
        adjusted: nb1BagsData.quantity,
        purchaseQty: primerBucketsData.quantity,
        cost: primerCost,
        overrideEnabled: primerBucketsData.overrideEnabled,
        extraRemaining: (primerBucketsData.quantity * 30) - nb1BagsData.quantity
    };

    // 12c. Drywall Cutting
    const dcItem = getItemData('drywall_cut');
    const dcAreaCalc = q.totalDrywallCutArea;
    const dcData = getQuantity('drywall_cut', Math.ceil(dcAreaCalc));
    const dcCost = dcData.quantity * dcItem.packagePrice;
    report.items['drywall_cut'] = {
        data: dcItem,
        measured: q.totalDrywallCutArea,
        adjusted: q.totalDrywallCutArea,
        purchaseQty: dcData.quantity,
        cost: dcCost,
        overrideEnabled: dcData.overrideEnabled,
        extraRemaining: 0
    };

    // 12d. Attic Insulation Removal
    const irItem = getItemData('insulation_removal');
    const irAreaCalc = q.totalInsulationRemoveArea;
    const irData = getQuantity('insulation_removal', Math.ceil(irAreaCalc));
    const irCost = irData.quantity * irItem.packagePrice;
    report.items['insulation_removal'] = {
        data: irItem,
        measured: q.totalInsulationRemoveArea,
        adjusted: q.totalInsulationRemoveArea,
        purchaseQty: irData.quantity,
        cost: irCost,
        overrideEnabled: irData.overrideEnabled,
        extraRemaining: 0
    };

    // 12e. Blown-in Attic Insulation
    const ibItem = getItemData('insulation_blowing');
    const ibAreaCalc = q.totalInsulationBlowArea;
    const ibData = getQuantity('insulation_blowing', Math.ceil(ibAreaCalc));
    const ibCost = ibData.quantity * ibItem.packagePrice;
    report.items['insulation_blowing'] = {
        data: ibItem,
        measured: q.totalInsulationBlowArea,
        adjusted: q.totalInsulationBlowArea,
        purchaseQty: ibData.quantity,
        cost: ibCost,
        overrideEnabled: ibData.overrideEnabled,
        extraRemaining: 0
    };

    // 13. Waterstop
    const wsItem = getItemData('waterstop');
    const wsWasteMultiplier = 1 + (settings.generalWaste / 100);
    const wsCoverageCalc = q.totalWaterstopArea * wsWasteMultiplier;
    const wsPailsCalc = Math.ceil(wsCoverageCalc / 2000);
    const wsPailsData = getQuantity('waterstop', wsPailsCalc);
    const wsCost = wsPailsData.quantity * wsItem.packagePrice;
    report.items['waterstop'] = {
        data: wsItem,
        measured: q.totalWaterstopArea,
        adjusted: wsCoverageCalc,
        purchaseQty: wsPailsData.quantity,
        cost: wsCost,
        overrideEnabled: wsPailsData.overrideEnabled,
        extraRemaining: (wsPailsData.quantity * 2000) - wsCoverageCalc
    };

    // 14. Floor Epoxy
    const epoxyItem = getItemData('floor_epoxy');
    const epoxyWasteMultiplier = 1 + (settings.generalWaste / 100);
    const epoxyCoverageCalc = q.totalEpoxyArea * epoxyWasteMultiplier;
    const epoxyKitsCalc = Math.ceil(epoxyCoverageCalc / 300);
    const epoxyKitsData = getQuantity('floor_epoxy', epoxyKitsCalc);
    const epoxyCost = epoxyKitsData.quantity * epoxyItem.packagePrice;
    report.items['floor_epoxy'] = {
        data: epoxyItem,
        measured: q.totalEpoxyArea,
        adjusted: epoxyCoverageCalc,
        purchaseQty: epoxyKitsData.quantity,
        cost: epoxyCost,
        overrideEnabled: epoxyKitsData.overrideEnabled,
        extraRemaining: (epoxyKitsData.quantity * 300) - epoxyCoverageCalc
    };

    // 15. Dehumidifier Stands
    const standItem = getItemData('dehumidifier_stands');
    // Compute required stands count (default 1 per permanent dehumidifier unless disabled in overrides)
    let standCountCalc = 0;
    if (pdData.quantity > 0) {
        let disabledCount = 0;
        if (costing.projectOverrides && costing.projectOverrides.standsDisabledCount !== undefined) {
            disabledCount = Math.max(0, parseInt(costing.projectOverrides.standsDisabledCount) || 0);
        }
        standCountCalc = Math.max(0, pdData.quantity - disabledCount);
    }
    const standPacksCalc = Math.ceil(standCountCalc / 4);
    const standPacksData = getQuantity('dehumidifier_stands', standPacksCalc);
    const standCost = standPacksData.quantity * standItem.packagePrice;
    report.items['dehumidifier_stands'] = {
        data: standItem,
        measured: standCountCalc,
        adjusted: standCountCalc,
        purchaseQty: standPacksData.quantity,
        cost: standCost,
        overrideEnabled: standPacksData.overrideEnabled,
        extraRemaining: (standPacksData.quantity * 4) - standCountCalc
    };

    // 16. Sump Basin and Drain Stone Package
    const stoneItem = getItemData('sump_basin_drain_stone');
    const stonePacksCalc = projState.sumpPumps.length; // 1 package per basin
    const stonePacksData = getQuantity('sump_basin_drain_stone', stonePacksCalc);
    const stoneCost = stonePacksData.quantity * stoneItem.packagePrice;
    report.items['sump_basin_drain_stone'] = {
        data: stoneItem,
        measured: stonePacksCalc,
        adjusted: stonePacksCalc,
        purchaseQty: stonePacksData.quantity,
        cost: stoneCost,
        overrideEnabled: stonePacksData.overrideEnabled,
        extraRemaining: 0
    };

    // Accumulate Material / Equipment / Supply categories
    const categoriesMap = {
        vapor_barrier_tape: 'supply',
        vapor_barrier: 'material',
        spray_foam: 'material',
        carbon_fiber: 'material',
        benefect: 'material',
        rmr: 'material',
        n95_masks: 'supply',
        sump_pump_half_hp: 'equipment',
        wifi_sump_float: 'equipment',
        permanent_dehumidifier: 'equipment',
        garbage_bags: 'supply',
        nb1: 'material',
        nb1_primer: 'material',
        drywall_cut: 'material',
        insulation_removal: 'material',
        insulation_blowing: 'material',
        waterstop: 'material',
        floor_epoxy: 'material',
        dehumidifier_stands: 'supply',
        sump_basin_drain_stone: 'material'
    };

    Object.keys(report.items).forEach(id => {
        const itemInfo = report.items[id];
        
        // Determine if item is excluded individually or via the global vapor barrier setting
        const isExcluded = (costing.excludedItems && costing.excludedItems[id] === true) ||
                           (settings.useVaporBarrier === false && (id === 'vapor_barrier' || id === 'vapor_barrier_tape'));
        
        if (isExcluded) {
            itemInfo.purchaseQty = 0;
            itemInfo.cost = 0;
            itemInfo.extraRemaining = 0;
            itemInfo.excluded = true;
        }

        if (itemInfo.data.active && !isExcluded) {
            const cat = categoriesMap[id] || 'material';
            if (cat === 'material') {
                report.subtotals.material += itemInfo.cost;
            } else if (cat === 'equipment') {
                report.subtotals.equipment += itemInfo.cost;
            } else if (cat === 'supply') {
                report.subtotals.supply += itemInfo.cost;
            }

            if (itemInfo.data.taxable) {
                report.subtotals.taxable += itemInfo.cost;
            }
        }
    });

    // 17. Water Damage Equipment Rentals
    let rentalSubtotal = 0;
    const dehumRentalUnits = Math.max(0, parseInt(costing.rentals.dehumidifierUnits) || 0);
    const dehumRentalDays = Math.max(0, parseInt(costing.rentals.dehumidifierDays) || 0);
    const dehumRentalCost = dehumRentalUnits * dehumRentalDays * 100;
    rentalSubtotal += dehumRentalCost;
    if (costing.rentals.dehumidifierTaxable && dehumRentalCost > 0) {
        report.subtotals.taxable += dehumRentalCost;
    }

    const airMoverUnits = Math.max(0, parseInt(costing.rentals.airMoverUnits) || 0);
    const airMoverDays = Math.max(0, parseInt(costing.rentals.airMoverDays) || 0);
    const airMoverCost = airMoverUnits * airMoverDays * 38;
    rentalSubtotal += airMoverCost;
    if (costing.rentals.airMoverTaxable && airMoverCost > 0) {
        report.subtotals.taxable += airMoverCost;
    }

    const airScrubberUnits = Math.max(0, parseInt(costing.rentals.airScrubberUnits) || 0);
    const airScrubberDays = Math.max(0, parseInt(costing.rentals.airScrubberDays) || 0);
    const airScrubberCost = airScrubberUnits * airScrubberDays * 105;
    rentalSubtotal += airScrubberCost;
    if (costing.rentals.airScrubberTaxable && airScrubberCost > 0) {
        report.subtotals.taxable += airScrubberCost;
    }

    // Optional rental charges
    if (Array.isArray(costing.rentals.optionalCharges)) {
        costing.rentals.optionalCharges.forEach(ch => {
            const qty = Math.max(0, parseFloat(ch.qty) || 0);
            const rate = Math.max(0, parseFloat(ch.rate) || 0);
            const cost = qty * rate;
            rentalSubtotal += cost;
            if (ch.taxable && cost > 0) {
                report.subtotals.taxable += cost;
            }
        });
    }
    report.subtotals.rental = rentalSubtotal;

    // Calculate Michigan tax (6% default)
    const taxRate = Math.max(0, settings.taxRate) / 100;
    report.subtotals.tax = report.subtotals.taxable * taxRate;

    // 18. Labor System
    let laborCost = 0;
    let laborHours = 0;

    const laborMode = costing.labor.mode || 'project';
    if (laborMode === 'project' || laborMode === 'combined') {
        const crew = Math.max(0, parseFloat(costing.labor.projectCrewSize) || 0);
        const days = Math.max(0, parseFloat(costing.labor.projectWorkdays) || 0);
        const hours = Math.max(0, parseFloat(costing.labor.projectHoursPerDay) || 0);
        const rate = Math.max(0, parseFloat(costing.labor.projectLaborRate) || 0);

        laborHours += crew * days * hours;
        laborCost += laborHours * rate;
    }
    if (laborMode === 'detailed' || laborMode === 'combined') {
        if (Array.isArray(costing.labor.detailedLines)) {
            costing.labor.detailedLines.forEach(line => {
                const workers = Math.max(0, parseFloat(line.workers) || 0);
                const hours = Math.max(0, parseFloat(line.hours) || 0);
                const rate = Math.max(0, parseFloat(line.rate) || 0);
                const lineHours = workers * hours;
                laborHours += lineHours;
                laborCost += lineHours * rate;
            });
        }
    }
    report.subtotals.labor = laborCost;
    report.laborHours = laborHours;

    // If materials are selected (or active in project) but no labor has been configured
    const hasActiveMaterials = projState.rooms.length > 0 || projState.sumpPumps.length > 0 || permDehumCalc > 0;
    if (hasActiveMaterials && laborHours === 0) {
        report.warnings['labor'] = "Labor Missing: Material scope exists, but no labor hours are configured.";
    }

    // 19. Custom Cost Items
    let customDirect = 0;
    let customOverheadBasis = 0;
    let customMarkupBasis = 0;

    if (Array.isArray(costing.customItems)) {
        costing.customItems.forEach(item => {
            const qty = Math.max(0, parseFloat(item.qty) || 0);
            const cost = Math.max(0, parseFloat(item.unitCost) || 0);
            const waste = 1 + (Math.max(0, parseFloat(item.waste) || 0) / 100);
            const baseCost = qty * cost * waste;
            
            // Associated labor hours
            const lHours = Math.max(0, parseFloat(item.laborHours) || 0);
            const lRate = Math.max(0, parseFloat(item.laborRate) || 0);
            const itemLaborCost = lHours * lRate;

            const totalItemCost = baseCost + itemLaborCost;
            customDirect += totalItemCost;

            if (item.taxable && baseCost > 0) {
                // Adjust tax subtotal and add tax to direct cost
                const itemTax = baseCost * taxRate;
                customDirect += itemTax;
                report.subtotals.tax += itemTax;
                report.subtotals.taxable += baseCost;
            }

            if (item.includeInOverhead) {
                customOverheadBasis += totalItemCost;
            }
            if (item.includeInMarkup) {
                customMarkupBasis += totalItemCost;
            }
        });
    }
    report.subtotals.custom = customDirect;

    // 20. Direct Project Cost
    // Direct Cost = Raw purchase subtotal (materials, equipment, supply) + rentals + tax + labor + custom costs
    const rawPurchaseSubtotal = report.subtotals.material + report.subtotals.equipment + report.subtotals.supply;
    report.subtotals.direct = rawPurchaseSubtotal + report.subtotals.rental + report.subtotals.tax + report.subtotals.labor + report.subtotals.custom;

    // 21. Overhead Amount
    // Overhead = (Direct Cost - Custom direct cost not included in overhead) * Overhead Percentage
    const overheadPct = Math.max(0, settings.overhead) / 100;
    // Calculate custom portion to exclude
    let excludedOverhead = 0;
    if (Array.isArray(costing.customItems)) {
        costing.customItems.forEach(item => {
            if (!item.includeInOverhead) {
                const qty = Math.max(0, parseFloat(item.qty) || 0);
                const cost = Math.max(0, parseFloat(item.unitCost) || 0);
                const waste = 1 + (Math.max(0, parseFloat(item.waste) || 0) / 100);
                const baseCost = qty * cost * waste;
                const lHours = Math.max(0, parseFloat(item.laborHours) || 0);
                const lRate = Math.max(0, parseFloat(item.laborRate) || 0);
                const itemLaborCost = lHours * lRate;
                let taxAmount = 0;
                if (item.taxable) {
                    taxAmount = baseCost * taxRate;
                }
                excludedOverhead += baseCost + itemLaborCost + taxAmount;
            }
        });
    }
    const overheadBasisCost = Math.max(0, report.subtotals.direct - excludedOverhead);
    report.subtotals.overhead = overheadBasisCost * overheadPct;

    // 22. Cost Basis
    // Cost Basis = Direct Cost + Overhead
    report.subtotals.costBasis = report.subtotals.direct + report.subtotals.overhead;

    // 23. Selling Price & Margins
    let markupAmount = 0;
    let sellingPrice = 0;
    let expectedProfit = 0;
    let actualMargin = 0;

    // Calculate excluded markup cost portion
    let excludedMarkup = 0;
    if (Array.isArray(costing.customItems)) {
        costing.customItems.forEach(item => {
            if (!item.includeInMarkup) {
                const qty = Math.max(0, parseFloat(item.qty) || 0);
                const cost = Math.max(0, parseFloat(item.unitCost) || 0);
                const waste = 1 + (Math.max(0, parseFloat(item.waste) || 0) / 100);
                const baseCost = qty * cost * waste;
                const lHours = Math.max(0, parseFloat(item.laborHours) || 0);
                const lRate = Math.max(0, parseFloat(item.laborRate) || 0);
                const itemLaborCost = lHours * lRate;
                let taxAmount = 0;
                if (item.taxable) {
                    taxAmount = baseCost * taxRate;
                }
                excludedMarkup += baseCost + itemLaborCost + taxAmount;
                // Also add its portion of overhead if it was included in overhead
                if (item.includeInOverhead) {
                    excludedMarkup += (baseCost + itemLaborCost + taxAmount) * overheadPct;
                }
            }
        });
    }

    const markupBasisCost = Math.max(0, report.subtotals.costBasis - excludedMarkup);

    if (settings.pricingMode === 'markup') {
        const markupPct = Math.max(0, settings.markup) / 100;
        markupAmount = markupBasisCost * markupPct;
        sellingPrice = report.subtotals.costBasis + markupAmount;
    } else if (settings.pricingMode === 'target-margin') {
        const targetMarginPct = Math.min(99.9, Math.max(0, settings.targetGrossMargin)) / 100;
        if (targetMarginPct >= 1.0) {
            // Guard against divide by zero or infinite price
            sellingPrice = report.subtotals.costBasis;
        } else {
            // Price = excluded costs + basis costs / (1 - margin)
            sellingPrice = excludedMarkup + (markupBasisCost / (1 - targetMarginPct));
        }
        markupAmount = sellingPrice - report.subtotals.costBasis;
    }

    expectedProfit = sellingPrice - report.subtotals.costBasis;
    actualMargin = sellingPrice > 0 ? (expectedProfit / sellingPrice * 100) : 0;

    const internalLaborCost = report.laborHours * settings.loadedLaborRate;
    const actualDirectCost = report.subtotals.direct - report.subtotals.labor + internalLaborCost;
    
    report.subtotals.internalLabor = internalLaborCost;
    report.subtotals.actualDirectCost = actualDirectCost;
    report.subtotals.trueNetProfit = sellingPrice - actualDirectCost - report.subtotals.overhead; // subtract overhead as it is an internal cost/expense

    report.subtotals.markup = markupAmount;
    report.subtotals.sellingPrice = sellingPrice;
    report.subtotals.expectedGrossProfit = expectedProfit;
    report.subtotals.actualMarginPercent = actualMargin;

    return report;
}

// Strictly sanitized customer export model (Whitelisted properties only)
function buildCustomerExportModel(projState) {
    const rawQuantities = calculateProjectQuantities(projState);

    // Whitelist customer-facing details. DO NOT copy the costing object.
    const model = {
        customerName: document.getElementById('customer-name').value || 'Not Specified',
        customerAddress: document.getElementById('customer-address').value || 'Not Specified',
        currentLevelId: projState.currentLevelId,
        levels: (projState.levels || []).map(l => ({ id: l.id, name: l.name, height: l.height })),
        rooms: (projState.rooms || []).map(r => ({
            id: r.id,
            name: r.name,
            type: r.type,
            w: r.w,
            l: r.l,
            h: r.h,
            levelId: r.levelId,
            foamBoard: r.foamBoard,
            foamBondPockets: r.foamBondPockets,
            carbonStraps: r.carbonStraps,
            floorPerimeterStrap: r.floorPerimeterStrap,
            nb1Height: r.nb1Height,
            drywallHeight: r.drywallHeight,
            drywallWalls: Array.isArray(r.drywallWalls) ? [...r.drywallWalls] : null,
            removeInsulation: r.removeInsulation,
            blowInInsulation: r.blowInInsulation,
            joists: r.joists || 'none',
            openings: (r.openings || []).map(o => ({ type: o.type, wall: o.wall, w: o.w, h: o.h, offset: o.offset }))
        })),
        sumpPumps: (projState.sumpPumps || []).map(sp => ({ id: sp.id, name: sp.name, x: sp.x, y: sp.y, levelId: sp.levelId })),
        dehumidifiers: (projState.dehumidifiers || []).map(dh => ({ id: dh.id, name: dh.name, x: dh.x, y: dh.y, levelId: dh.levelId })),
        dischargeLines: (projState.dischargeLines || []).map(dl => ({ id: dl.id, label: dl.label, length: dl.length, x1: dl.x1, y1: dl.y1, x2: dl.x2, y2: dl.y2, levelId: dl.levelId })),
        interiorPipes: (projState.interiorPipes || []).map(ip => ({ id: ip.id, length: ip.length, x1: ip.x1, y1: ip.y1, x2: ip.x2, y2: ip.y2, levelId: ip.levelId })),
        stanchions: (projState.stanchions || []).map(st => ({ id: st.id, type: st.type, x: st.x, y: st.y, levelId: st.levelId })),
        mainBeams: (projState.mainBeams || []).map(bm => ({ id: bm.id, x1: bm.x1, y1: bm.y1, x2: bm.x2, y2: bm.y2, levelId: bm.levelId })),
        
        // Clean quantity totals
        quantities: {
            roomsCount: rawQuantities.totalRooms,
            floorArea: rawQuantities.totalFloorArea,
            wallArea: rawQuantities.totalWallArea,
            ceilingArea: rawQuantities.totalCeilingArea,
            volume: rawQuantities.totalVolume,
            perimeter: rawQuantities.totalPerimeter,
            xpsSheets: Math.ceil(rawQuantities.totalXpsSheets),
            pvcSticks: rawQuantities.plumbingEst.sticks,
            pvc90s: rawQuantities.plumbingEst.elbow90,
            pvc45s: rawQuantities.plumbingEst.elbow45,
            drainTile: rawQuantities.plumbingEst.drainTile,
            
            // Placed elements checklist
            sumpBasins: rawQuantities.totalRooms ? projState.sumpPumps.length : 0,
            sumpFittings: {
                bushing3to2: rawQuantities.plumbingEst.bushing3to2,
                tee3x3x2: rawQuantities.plumbingEst.tee3x3x2,
                elbow3in90: rawQuantities.plumbingEst.elbow3in90,
                screwAdapter1_5: rawQuantities.plumbingEst.screwAdapter1_5,
                checkValve2: rawQuantities.plumbingEst.checkValve2,
                yFitting2: rawQuantities.plumbingEst.yFitting2
            },
            vaporLinerArea: rawQuantities.totalLinerArea,
            carbonFiberLen: rawQuantities.totalCarbonFiberLen,
            nb1Bags: Math.ceil(rawQuantities.totalNb1Area / ((projState.costing && projState.costing.settings && projState.costing.settings.nb1SqFtPerBag) || 8)),
            nb1Area: rawQuantities.totalNb1Area,
            drywallCutArea: rawQuantities.totalDrywallCutArea,
            insulationRemoveArea: rawQuantities.totalInsulationRemoveArea,
            insulationBlowArea: rawQuantities.totalInsulationBlowArea,
            sprayFoamCans: rawQuantities.totalSprayFoamCans
        }
    };
    return model;
}

// Development Safety Scanner to verify zero costing terms exist in customer output
function scanCustomerReportForPricingData(htmlContent) {
    const prohibitedTerms = [
        "unit cost",
        "supplier price",
        "markup",
        "gross profit",
        "gross margin",
        "labor rate",
        "overhead percentage",
        "taxable subtotal",
        "internal selling price",
        "target margin"
    ];

    const lowerHTML = htmlContent.toLowerCase();
    for (let i = 0; i < prohibitedTerms.length; i++) {
        const term = prohibitedTerms[i];
        if (lowerHTML.indexOf(term) !== -1) {
            console.error("DEVELOPER ERROR: Prohibited internal cost term [" + term + "] detected in customer export report.");
            return {
                safe: false,
                offendingTerm: term
            };
        }
    }
    return { safe: true };
}

// Bind to window context
window.initDefaultCosting = initDefaultCosting;
window.formatCurrency = formatCurrency;
window.calculateProjectQuantities = calculateProjectQuantities;
window.calculateProjectCosts = calculateProjectCosts;
window.buildCustomerExportModel = buildCustomerExportModel;
window.scanCustomerReportForPricingData = scanCustomerReportForPricingData;
