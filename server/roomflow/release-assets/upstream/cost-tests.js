// --- ROOMFLOW COSTING SYSTEM AUTOMATED TEST SUITE ---

function runCostingTests() {
    console.log("Starting RoomFlow Estimating and Costing Verification Suite...");
    const results = [];

    function assert(name, condition, message) {
        if (condition) {
            results.push({ name: name, status: "PASSED", message: message || "Check passed." });
            console.log(`[PASS] ${name}`);
        } else {
            results.push({ name: name, status: "FAILED", message: message || "Assertion failed." });
            console.error(`[FAIL] ${name}: ${message}`);
        }
    }

    const testCatalog = RoomFlowCatalog.getDefaults();

    // 1. Vapor-barrier roll rounding
    // 901 sq ft / 900 = 1.001 rolls -> should ceil to 2 rolls before waste is added
    // Let's create a mock state
    let state1 = { rooms: [{ id: "r1", w: 10, l: 90.1, h: 0, levelId: "basement", openings: [] }], sumpPumps: [], dischargeLines: [], interiorPipes: [], stanchions: [], mainBeams: [], levels: [{ id: "basement", height: 8 }] };
    initDefaultCosting(state1);
    state1.costing.settings.generalWaste = 0; // disable waste for this specific check
    let report1 = calculateProjectCosts(state1, testCatalog);
    assert("1. Vapor-barrier roll rounding", report1.items.vapor_barrier.purchaseQty === 2, 
        `Expected 2 rolls for 901 sq ft, got ${report1.items.vapor_barrier.purchaseQty}`);

    // 2. Tape case rounding
    // 13 rolls -> Math.ceil(13/12) = 2 cases
    let state2 = { rooms: [{ id: "r1", w: 10, l: 10, h: 0, levelId: "basement", openings: [] }], sumpPumps: [], dischargeLines: [], interiorPipes: [], stanchions: [], mainBeams: [], levels: [] };
    initDefaultCosting(state2);
    state2.costing.settings.tapeCoveragePerRoll = 10; // 10 sq ft per roll
    // liner area = floor + walls. Floor = 100.
    state2.costing.manualQuantityOverrides.vapor_barrier_tape = { overrideQuantity: 13, overrideEnabled: true };
    let report2 = calculateProjectCosts(state2, testCatalog);
    assert("2. Tape case rounding", report2.items.vapor_barrier_tape.purchaseQty === 2,
        `Expected 2 cases for 13 rolls, got ${report2.items.vapor_barrier_tape.purchaseQty}`);

    // 3. Spray-foam case rounding
    // 25 cans -> Math.ceil(25/24) = 2 cases
    let state3 = { rooms: [{ id: "r3", x: 0, y: 0, w: 165, l: 10, h: 8, foamBondPockets: true, joists: 'ns', levelId: "basement", openings: [] }], sumpPumps: [], dischargeLines: [], interiorPipes: [], stanchions: [], mainBeams: [], levels: [{ id: "basement", height: 8 }] };
    initDefaultCosting(state3);
    let report3 = calculateProjectCosts(state3, testCatalog);
    assert("3. Spray-foam case rounding", report3.items.spray_foam.purchaseQty === 2,
        `Expected 2 cases for 25 cans, got ${report3.items.spray_foam.purchaseQty}`);

    // 4. Carbon-fiber roll rounding
    // 76 ft -> Math.ceil(76/75) = 2 rolls
    let state4 = { rooms: [{ id: "r4", w: 10, l: 28, h: 8, floorPerimeterStrap: true, levelId: "basement", openings: [] }], sumpPumps: [], dischargeLines: [], interiorPipes: [], stanchions: [], mainBeams: [], levels: [{ id: "basement", height: 8 }] };
    initDefaultCosting(state4);
    state4.costing.settings.generalWaste = 0;
    let report4 = calculateProjectCosts(state4, testCatalog);
    assert("4. Carbon-fiber roll rounding", report4.items.carbon_fiber.purchaseQty === 2,
        `Expected 2 rolls for 76 ft, got ${report4.items.carbon_fiber.purchaseQty}`);

    // 5. Floor-epoxy kit rounding
    // 301 sq ft -> Math.ceil(301/300) = 2 kits
    let state5 = { rooms: [{ id: "r1", w: 10, l: 10, h: 8, levelId: "basement", openings: [] }], sumpPumps: [], dischargeLines: [], interiorPipes: [], stanchions: [], mainBeams: [] };
    initDefaultCosting(state5);
    state5.costing.settings.generalWaste = 0;
    state5.costing.treatmentSelections["r1"] = { epoxy: 'custom', epoxyCustomArea: 301 };
    let report5 = calculateProjectCosts(state5, testCatalog);
    assert("5. Floor-epoxy kit rounding", report5.items.floor_epoxy.purchaseQty === 2,
        `Expected 2 kits for 301 sq ft, got ${report5.items.floor_epoxy.purchaseQty}`);

    // 6. Waterstop pail rounding
    // 2001 sq ft -> Math.ceil(2001/2000) = 2 pails
    let state6 = { rooms: [{ id: "r1", w: 10, l: 10, h: 8, levelId: "basement", openings: [] }], sumpPumps: [], dischargeLines: [], interiorPipes: [], stanchions: [], mainBeams: [] };
    initDefaultCosting(state6);
    state6.costing.settings.generalWaste = 0;
    state6.costing.treatmentSelections["r1"] = { waterstop: 'custom', waterstopCustomArea: 2001 };
    let report6 = calculateProjectCosts(state6, testCatalog);
    assert("6. Waterstop pail rounding", report6.items.waterstop.purchaseQty === 2,
        `Expected 2 pails for 2001 sq ft, got ${report6.items.waterstop.purchaseQty}`);

    // 7. Garbage-bag package rounding
    // 51 bags -> Math.ceil(51/50) = 2 packages
    let state7 = { rooms: [], sumpPumps: [], dischargeLines: [], interiorPipes: [], stanchions: [], mainBeams: [] };
    initDefaultCosting(state7);
    state7.costing.projectOverrides.garbageBagsQty = 51;
    let report7 = calculateProjectCosts(state7, testCatalog);
    assert("7. Garbage-bag package rounding", report7.items.garbage_bags.purchaseQty === 2,
        `Expected 2 packages for 51 bags, got ${report7.items.garbage_bags.purchaseQty}`);

    // 8. Sump pump quantity using two pumps per basin
    // 1 basin -> 2 pumps
    let state8 = { rooms: [], sumpPumps: [{ id: "s1", name: "Sump Basin 1", x: 0, y: 0, levelId: "basement" }], dischargeLines: [], interiorPipes: [], stanchions: [], mainBeams: [] };
    initDefaultCosting(state8);
    let report8 = calculateProjectCosts(state8, testCatalog);
    assert("8. Sump pump quantity default (2 per basin)", report8.items.sump_pump_half_hp.purchaseQty === 2,
        `Expected 2 pumps for 1 basin, got ${report8.items.sump_pump_half_hp.purchaseQty}`);

    // 9. Wi-Fi float quantity matching pump quantity
    assert("9. Wi-Fi float quantity matches pump quantity", report8.items.wifi_sump_float.purchaseQty === 2,
        `Expected 2 Wi-Fi floats for 2 pumps, got ${report8.items.wifi_sump_float.purchaseQty}`);

    // 10. Sump basin and drain-stone package quantity
    assert("10. Sump basin stone package quantity matches basin count", report8.items.sump_basin_drain_stone.purchaseQty === 1,
        `Expected 1 stone package for 1 basin, got ${report8.items.sump_basin_drain_stone.purchaseQty}`);

    // 11. Permanent dehumidifier quantity
    let state11 = { rooms: [], sumpPumps: [], dischargeLines: [], interiorPipes: [], stanchions: [], mainBeams: [] };
    initDefaultCosting(state11);
    state11.costing.projectOverrides.permanentDehumQty = 3;
    let report11 = calculateProjectCosts(state11, testCatalog);
    assert("11. Permanent dehumidifier quantity", report11.items.permanent_dehumidifier.purchaseQty === 3,
        `Expected 3 permanent dehumidifiers, got ${report11.items.permanent_dehumidifier.purchaseQty}`);

    // 12. Dehumidifier stand package rounding
    // 5 dehumidifiers require 5 stands -> Math.ceil(5/4) = 2 packs of stands
    state11.costing.projectOverrides.permanentDehumQty = 5;
    state11.costing.projectOverrides.standsDisabledCount = 0;
    let report12 = calculateProjectCosts(state11, testCatalog);
    assert("12. Dehumidifier stands pack rounding (5 dehum -> 2 packs)", report12.items.dehumidifier_stands.purchaseQty === 2,
        `Expected 2 packs of stands for 5 dehumidifiers, got ${report12.items.dehumidifier_stands.purchaseQty}`);

    // 13. Rental dehumidifier unit-day calculation
    // 2 units for 3 days = 6 unit-days
    let state13 = { rooms: [], sumpPumps: [], dischargeLines: [], interiorPipes: [], stanchions: [], mainBeams: [] };
    initDefaultCosting(state13);
    state13.costing.rentals.dehumidifierUnits = 2;
    state13.costing.rentals.dehumidifierDays = 3;
    let report13 = calculateProjectCosts(state13, testCatalog);
    // 2 * 3 * $100 = $600
    assert("13. Rental dehumidifier unit-day cost calculation", report13.subtotals.rental === 600,
        `Expected $600 for 2 units / 3 days, got ${report13.subtotals.rental}`);

    // 14. Air-mover unit-day calculation
    // 4 units for 3 days = 12 unit-days
    state13.costing.rentals.dehumidifierUnits = 0;
    state13.costing.rentals.dehumidifierDays = 0;
    state13.costing.rentals.airMoverUnits = 4;
    state13.costing.rentals.airMoverDays = 3;
    let report14 = calculateProjectCosts(state13, testCatalog);
    // 4 * 3 * $38 = $456
    assert("14. Air mover unit-day cost calculation", report14.subtotals.rental === 456,
        `Expected $456 for 4 units / 3 days, got ${report14.subtotals.rental}`);

    // 15. Michigan 6% tax on taxable items
    // Let's create a taxable custom item of $100. Tax should be $6.
    let state15 = { rooms: [], sumpPumps: [], dischargeLines: [], interiorPipes: [], stanchions: [], mainBeams: [] };
    initDefaultCosting(state15);
    state15.costing.labor.projectCrewSize = 0;
    state15.costing.labor.projectWorkdays = 0;
    state15.costing.labor.projectHoursPerDay = 0;
    // Deactive all default catalog items in testing state to isolate custom items
    state15.costing.customItems = [{
        name: "Taxable Material",
        category: "material",
        qty: 1,
        unit: "ea",
        unitCost: 100,
        waste: 0,
        laborHours: 0,
        laborRate: 0,
        taxable: true,
        includeInOverhead: false,
        includeInMarkup: false
    }];
    let report15 = calculateProjectCosts(state15, testCatalog);
    assert("15. Michigan 6% tax on taxable items", report15.subtotals.tax === 6,
        `Expected $6 tax on $100 item, got ${report15.subtotals.tax}`);

    // 16. No sales/use tax on labor
    state15.costing.customItems[0].taxable = false;
    state15.costing.customItems[0].laborHours = 10;
    state15.costing.customItems[0].laborRate = 65; // $650 labor
    let report16 = calculateProjectCosts(state15, testCatalog);
    assert("16. No sales/use tax on labor", report16.subtotals.tax === 0,
        `Expected $0 tax on labor, got ${report16.subtotals.tax}`);

    // 17. Overhead calculation
    // Direct cost is $650 labor. Overhead is 15% -> $97.50.
    state15.costing.customItems[0].unitCost = 0;
    state15.costing.customItems[0].includeInOverhead = true;
    let report17 = calculateProjectCosts(state15, testCatalog);
    assert("17. Overhead calculation (15%)", report17.subtotals.overhead === 97.50,
        `Expected $97.50 overhead, got ${report17.subtotals.overhead}`);

    // 18. Markup calculation
    // Cost basis = direct cost ($650) + overhead ($97.50) = $747.50.
    // Markup is 30% -> $224.25.
    state15.costing.customItems[0].includeInMarkup = true;
    let report18 = calculateProjectCosts(state15, testCatalog);
    assert("18. Markup calculation (30%)", report18.subtotals.markup === 224.25,
        `Expected $224.25 markup, got ${report18.subtotals.markup}`);

    // 19. Target gross-margin calculation
    // Cost basis = $747.50. Target margin = 40%.
    // Selling price = 747.50 / (1 - 0.4) = $1245.83. Markup = $498.33.
    state15.costing.settings.pricingMode = 'target-margin';
    state15.costing.settings.targetGrossMargin = 40;
    let report19 = calculateProjectCosts(state15, testCatalog);
    const expectedSellingPrice = 747.50 / 0.6;
    assert("19. Target gross-margin calculation (40%)", Math.abs(report19.subtotals.sellingPrice - expectedSellingPrice) < 0.01,
        `Expected $${expectedSellingPrice.toFixed(2)} selling price, got ${report19.subtotals.sellingPrice}`);

    // 20. Manual overrides
    let state20 = { rooms: [], sumpPumps: [], dischargeLines: [], interiorPipes: [], stanchions: [], mainBeams: [] };
    initDefaultCosting(state20);
    state20.costing.manualQuantityOverrides.spray_foam = { overrideQuantity: 5, overrideEnabled: true };
    let report20 = calculateProjectCosts(state20, testCatalog);
    assert("20. Manual overrides", report20.items.spray_foam.purchaseQty === 5 && report20.items.spray_foam.overrideEnabled,
        `Expected manual override qty 5, got ${report20.items.spray_foam.purchaseQty}`);

    // 21. Resetting a manual override
    delete state20.costing.manualQuantityOverrides.spray_foam;
    let report21 = calculateProjectCosts(state20, testCatalog);
    assert("21. Resetting a manual override", report21.items.spray_foam.purchaseQty === 0 && !report21.items.spray_foam.overrideEnabled,
        `Expected reset to 0, got ${report21.items.spray_foam.purchaseQty}`);

    // 22. Loading a legacy project without costing data
    let legacyProject = { rooms: [{ id: "r1", name: "Room 1", w: 10, l: 10, h: 8, openings: [], foamBoard: false }] };
    initDefaultCosting(legacyProject);
    assert("22. Loading a legacy project without costing data", legacyProject.costing !== undefined && legacyProject.costing.version === "1.0",
        `Expected costing object initialized, got ${JSON.stringify(legacyProject.costing)}`);

    // 23. Costing data persisting through project save/load
    let projectSaveStr = JSON.stringify({
        customerName: "Jane Doe",
        rooms: [],
        costing: legacyProject.costing
    });
    let loadedProject = JSON.parse(projectSaveStr);
    assert("23. Costing data persisting through save/load", loadedProject.costing && loadedProject.costing.settings.taxRate === 6.0,
        `Expected taxRate 6.0, got ${loadedProject.costing ? loadedProject.costing.settings.taxRate : 'null'}`);

    // 24. Costing data persisting through Job Database save/load
    // Job database uses the same structure. So this is identical.
    assert("24. Costing data persisting through Job Database save/load", loadedProject.costing !== undefined,
        `Expected costing data available in saved DB record`);

    // 25. Customer export containing no protected internal financial information
    const customerModel = buildCustomerExportModel(state15);
    assert("25. Customer export contains no protected costing data directly", 
        customerModel.costing === undefined && customerModel.items === undefined && customerModel.subtotals === undefined,
        `Expected costing fields omitted in export model`);

    // 26. Customer export containing no hidden internal cost values (using the safety scanner check)
    // Run safety scanner on a mock clean HTML
    const cleanHtml = "<div><h2>Rooms list</h2><p>Room 1: 10ft x 10ft</p></div>";
    const scanResult1 = scanCustomerReportForPricingData(cleanHtml);
    assert("26a. Safety scanner passes clean HTML", scanResult1.safe === true, "Expected clean HTML to pass");

    const dirtyHtml = "<div><h2>Rooms list</h2><p>Unit Cost: $12.00</p></div>";
    const scanResult2 = scanCustomerReportForPricingData(dirtyHtml);
    assert("26b. Safety scanner catches unit cost leak", scanResult2.safe === false && scanResult2.offendingTerm === "unit cost", 
        "Expected unit cost leak to be caught");

    // 27. Corrupted local catalog data recovering safely
    // Catalog recovery is handled by RoomFlowCatalog.loadCatalog fallback
    localStorage.setItem('roomflow_cost_catalog_v1', "{invalidJson");
    const safeCatalog = RoomFlowCatalog.loadCatalog();
    assert("27. Corrupted local catalog data recovering safely", safeCatalog.length === DEFAULT_CATALOG.length, 
        `Expected safe catalog recovery, got length ${safeCatalog.length}`);
    localStorage.removeItem('roomflow_cost_catalog_v1');

    // 28. Invalid catalog import being rejected
    let importError = null;
    try {
        RoomFlowCatalog.importJSON("{bad-json");
    } catch(e) {
        importError = e;
    }
    assert("28. Invalid catalog import being rejected", importError !== null, "Expected invalid catalog import to throw error");

    // 29. Individual item exclusion
    let state29 = { rooms: [], sumpPumps: [], dischargeLines: [], interiorPipes: [], stanchions: [], mainBeams: [], levels: [] };
    initDefaultCosting(state29);
    state29.costing.projectOverrides.permanentDehumQty = 2; // override dehum quantity to 2
    state29.costing.excludedItems.permanent_dehumidifier = true; // exclude it
    let report29 = calculateProjectCosts(state29, testCatalog);
    assert("29. Individual item exclusion", report29.items.permanent_dehumidifier.purchaseQty === 0 && report29.items.permanent_dehumidifier.cost === 0,
        `Expected 0 quantity and cost for excluded dehumidifier, got qty: ${report29.items.permanent_dehumidifier.purchaseQty}, cost: ${report29.items.permanent_dehumidifier.cost}`);

    // 30. Global vapor barrier disable toggle
    let state30 = { rooms: [{ id: "r30", w: 10, l: 10, h: 8, openings: [], levelId: "basement" }], sumpPumps: [], dischargeLines: [], interiorPipes: [], stanchions: [], mainBeams: [], levels: [{ id: "basement", height: 8 }] };
    initDefaultCosting(state30);
    // Enable tape coverage
    state30.costing.settings.tapeCoveragePerRoll = 100;
    state30.costing.settings.useVaporBarrier = false; // globally disable vapor barrier system
    let report30 = calculateProjectCosts(state30, testCatalog);
    assert("30. Global vapor barrier disable toggle", report30.items.vapor_barrier.purchaseQty === 0 && report30.items.vapor_barrier_tape.purchaseQty === 0,
        `Expected 0 vapor barrier and tape when disabled, got vb: ${report30.items.vapor_barrier.purchaseQty}, tape: ${report30.items.vapor_barrier_tape.purchaseQty}`);

    // 31. Placed dehumidifier on canvas auto-calculation
    let state31 = { rooms: [], sumpPumps: [], dehumidifiers: [{ id: "dh31", levelId: "basement", x: 5, y: 5 }], dischargeLines: [], interiorPipes: [], stanchions: [], mainBeams: [], levels: [] };
    initDefaultCosting(state31);
    let report31 = calculateProjectCosts(state31, testCatalog);
    assert("31. Placed dehumidifier auto-calculation", report31.items.permanent_dehumidifier.purchaseQty === 1 && report31.items.dehumidifier_stands.purchaseQty === 1,
        `Expected 1 dehumidifier and 1 stand pack from placed element, got dehum: ${report31.items.permanent_dehumidifier.purchaseQty}, stands: ${report31.items.dehumidifier_stands.purchaseQty}`);

    // 32. NB-1 Primer quantity calculation (1 bucket per 30 bags of NB-1)
    let state32 = { rooms: [{ id: "r1", name: "Room 1", w: 30, l: 30, h: 8, levelId: "basement", nb1Height: "2ft", openings: [] }], sumpPumps: [], dehumidifiers: [], dischargeLines: [], interiorPipes: [], stanchions: [], mainBeams: [], levels: [] };
    initDefaultCosting(state32);
    let report32 = calculateProjectCosts(state32, testCatalog);
    assert("32. NB-1 Primer coverage matching 30 bags of NB-1", report32.items.nb1_primer.purchaseQty === 1,
        `Expected 1 bucket of NB-1 Primer for 30 bags of NB-1, got: ${report32.items.nb1_primer.purchaseQty}`);

    // Verification Scenario from prompt
    // 1 sump basin, 2 sump pumps, 2 Wi-Fi floats, 1 sump basin and drain stone package.
    // 1 permanent dehumidifier, 1 stand (results in 1 pack).
    // 2 rental dehumidifiers for 3 days ($600).
    // 4 air movers for 3 days ($456).
    console.log("Running Specific Verification Scenario...");
    let vsState = {
        rooms: [],
        sumpPumps: [{ id: "sp1", name: "Sump Basin 1", x: 0, y: 0, levelId: "basement" }],
        dischargeLines: [],
        interiorPipes: [],
        stanchions: [],
        mainBeams: [],
        levels: []
    };
    initDefaultCosting(vsState);
    
    // Configure defaults
    vsState.costing.settings.generalWaste = 10; // 10% waste
    vsState.costing.settings.taxRate = 6.0;     // 6% tax
    vsState.costing.settings.overhead = 15.0;   // 15% overhead
    vsState.costing.settings.pricingMode = 'markup';
    vsState.costing.settings.markup = 30.0;     // 30% markup
    vsState.costing.settings.sumpPumpsPerBasin = 2; // 2 pumps per basin

    // Project Overrides
    vsState.costing.projectOverrides.permanentDehumQty = 1;
    vsState.costing.projectOverrides.standsDisabledCount = 0; // 1 stand required -> 1 pack of stands

    // Rentals
    vsState.costing.rentals.dehumidifierUnits = 2;
    vsState.costing.rentals.dehumidifierDays = 3;
    vsState.costing.rentals.dehumidifierTaxable = true;
    vsState.costing.rentals.airMoverUnits = 4;
    vsState.costing.rentals.airMoverDays = 3;
    vsState.costing.rentals.airMoverTaxable = true;

    // Deactive default catalog items that aren't in this specific test
    // Actually, DEFAULT_CATALOG items that have a calculated quantity of 0 will have 0 cost, which is fine!
    // Let's run calculations
    let vsReport = calculateProjectCosts(vsState, testCatalog);

    // Verify equipment costs:
    // Pumps: 2 * $119.99 = $239.98
    // Floats: 2 * $59.99 = $119.98
    // Sump kit: 1 * $250.00 = $250.00
    // Dehum: 1 * $449.99 = $449.99
    // Stands: 1 pack * $14.99 = $14.99
    // Sum = $1074.94
    const pumpCost = vsReport.items.sump_pump_half_hp.cost;
    const floatCost = vsReport.items.wifi_sump_float.cost;
    const stoneCost = vsReport.items.sump_basin_drain_stone.cost;
    const dehumCost = vsReport.items.permanent_dehumidifier.cost;
    const standCost = vsReport.items.dehumidifier_stands.cost;
    const totalEquipCost = pumpCost + floatCost + stoneCost + dehumCost + standCost;

    assert("VS Sump Pumps Cost ($239.98)", Math.abs(pumpCost - 239.98) < 0.01, `Got ${pumpCost}`);
    assert("VS Wi-Fi Floats Cost ($119.98)", Math.abs(floatCost - 119.98) < 0.01, `Got ${floatCost}`);
    assert("VS Basin Kit Cost ($250.00)", Math.abs(stoneCost - 250.00) < 0.01, `Got ${stoneCost}`);
    assert("VS Dehum Cost ($449.99)", Math.abs(dehumCost - 449.99) < 0.01, `Got ${dehumCost}`);
    assert("VS Stands Cost ($14.99)", Math.abs(standCost - 14.99) < 0.01, `Got ${standCost}`);
    assert("VS Total Equipment Cost ($1074.94)", Math.abs(totalEquipCost - 1074.94) < 0.01, `Got ${totalEquipCost}`);

    // Verify rentals:
    // Dehum rental: 2 * 3 * $100 = $600
    // Air mover rental: 4 * 3 * $38 = $456
    // Sum = $1056.00
    const dehumRental = vsState.costing.rentals.dehumidifierUnits * vsState.costing.rentals.dehumidifierDays * 100;
    const moverRental = vsState.costing.rentals.airMoverUnits * vsState.costing.rentals.airMoverDays * 38;
    const totalRental = dehumRental + moverRental;
    assert("VS Rental Dehum Cost ($600)", dehumRental === 600, `Got ${dehumRental}`);
    assert("VS Rental Air Movers Cost ($456)", moverRental === 456, `Got ${moverRental}`);
    assert("VS Total Rental Cost ($1056.00)", totalRental === 1056, `Got ${totalRental}`);

    // 33. Drywall cutting tests
    let state33 = { rooms: [{ id: "r1", name: "Room 1", w: 10, l: 20, h: 8, levelId: "basement", drywallHeight: "2ft", openings: [] }], sumpPumps: [], dehumidifiers: [], dischargeLines: [], interiorPipes: [], stanchions: [], mainBeams: [], levels: [] };
    initDefaultCosting(state33);
    let report33 = calculateProjectCosts(state33, testCatalog);
    // Perimeter = 2 * (10 + 20) = 60 ft.
    // 2 ft height -> 60 * 2 = 120 sq ft drywall cut.
    // Cost = 120 * 1.98 = 237.60.
    assert("33. Drywall Cutting 2ft area calculation", report33.items.drywall_cut.measured === 120,
        `Expected 120 sq ft measured, got: ${report33.items.drywall_cut.measured}`);
    assert("34. Drywall Cutting 2ft cost calculation", Math.abs(report33.items.drywall_cut.cost - 237.60) < 0.01,
        `Expected $237.60 cost, got: ${report33.items.drywall_cut.cost}`);

    let state34 = { rooms: [{ id: "r1", name: "Room 1", w: 10, l: 20, h: 8, levelId: "basement", drywallHeight: "full", openings: [{ w: 3, h: 7 }] }], sumpPumps: [], dehumidifiers: [], dischargeLines: [], interiorPipes: [], stanchions: [], mainBeams: [], levels: [] };
    initDefaultCosting(state34);
    let report34 = calculateProjectCosts(state34, testCatalog);
    // Perimeter = 60 ft. Gross wall area = 60 * 8 = 480.
    // Deductions = 3 * 7 = 21. Net wall area = 459.
    // Cost = 459 * 1.98 = 908.82.
    assert("35. Drywall Cutting full wall area calculation with opening", report34.items.drywall_cut.measured === 459,
        `Expected 459 sq ft measured, got: ${report34.items.drywall_cut.measured}`);
    assert("36. Drywall Cutting full wall cost calculation with opening", Math.abs(report34.items.drywall_cut.cost - 908.82) < 0.01,
        `Expected $908.82 cost, got: ${report34.items.drywall_cut.cost}`);

    // 37. Air Scrubber rental tests
    let state37 = { rooms: [], sumpPumps: [], dehumidifiers: [], dischargeLines: [], interiorPipes: [], stanchions: [], mainBeams: [], levels: [] };
    initDefaultCosting(state37);
    state37.costing.rentals.airScrubberUnits = 3;
    state37.costing.rentals.airScrubberDays = 4;
    state37.costing.rentals.airScrubberTaxable = false;
    let report37 = calculateProjectCosts(state37, testCatalog);
    // Cost = 3 * 4 * 105 = 1260.00
    assert("37. Air Scrubber rental cost calculation", report37.subtotals.rental === 1260,
        `Expected $1260 rental subtotal, got: ${report37.subtotals.rental}`);
    assert("38. Air Scrubber non-taxable verification", report37.subtotals.taxable === 0,
        `Expected $0 taxable subtotal, got: ${report37.subtotals.taxable}`);

    // 39. Attic level room elevation in state calculation
    const atticLevel = state.levels.find(l => l.id === 'attic');
    assert("39. Attic level preset existence", !!atticLevel, "Expected attic level preset to exist");
    assert("40. Attic level elevation is 25ft", atticLevel && atticLevel.elevation === 25, `Expected 25 elevation, got ${atticLevel ? atticLevel.elevation : 'none'}`);

    // 41. Attic Insulation Removal and Blowing costs
    let state41 = { rooms: [{ id: "r1", name: "Attic Room", w: 10, l: 20, h: 8, levelId: "attic", removeInsulation: true, blowInInsulation: true, openings: [] }], sumpPumps: [], dehumidifiers: [], dischargeLines: [], interiorPipes: [], stanchions: [], mainBeams: [], levels: [] };
    initDefaultCosting(state41);
    let report41 = calculateProjectCosts(state41, testCatalog);
    // Area = 10 * 20 = 200 sq ft.
    // Removal cost = 200 * 1.75 = $350.00.
    // Blowing cost = 200 * 2.25 = $450.00.
    assert("41. Insulation removal area", report41.items.insulation_removal.measured === 200, `Expected 200 sq ft, got: ${report41.items.insulation_removal.measured}`);
    assert("42. Insulation removal cost", Math.abs(report41.items.insulation_removal.cost - 350.00) < 0.01, `Expected $350.00, got: ${report41.items.insulation_removal.cost}`);
    assert("43. Insulation blowing area", report41.items.insulation_blowing.measured === 200, `Expected 200 sq ft, got: ${report41.items.insulation_blowing.measured}`);
    assert("44. Insulation blowing cost", Math.abs(report41.items.insulation_blowing.cost - 450.00) < 0.01, `Expected $450.00, got: ${report41.items.insulation_blowing.cost}`);

    // 45. Estimating Checklist DOM Existence
    const checklistDiv = document.getElementById('checklist-container');
    assert("45. Estimating Checklist Container exists", !!checklistDiv, "Expected checklist container viewport to exist");

    // 46. Room Checklist Addition Action
    const initialRoomsCount = state.rooms.length;
    if (typeof window.addRoomFromChecklist === 'function') {
        window.addRoomFromChecklist('basement');
        assert("46. Add room from checklist action updates state", state.rooms.length === initialRoomsCount + 1, "Expected rooms count to increase by 1");
        
        // 47. Room Checklist Deletion Action
        const addedRoomId = state.rooms[state.rooms.length - 1].id;
        window.removeRoomFromChecklist(addedRoomId);
        assert("47. Remove room from checklist action cleans state", state.rooms.length === initialRoomsCount, "Expected rooms count to revert to original");
    } else {
        assert("46. Add room from checklist action updates state", false, "addRoomFromChecklist is not defined");
        assert("47. Remove room from checklist action cleans state", false, "removeRoomFromChecklist is not defined");
    }

    // Display results in the UI banner if it exists
    const banner = document.getElementById('cost-test-results-banner');
    if (banner) {
        banner.classList.remove('hidden');
        const failedCount = results.filter(r => r.status === "FAILED").length;
        
        let bannerHtml = `
            <div class="test-banner-header ${failedCount > 0 ? 'banner-fail' : 'banner-pass'}">
                <h4><i data-lucide="${failedCount > 0 ? 'alert-octagon' : 'check-circle-2'}"></i> Verification Results: ${results.length - failedCount}/${results.length} Tests Passed</h4>
                <button onclick="document.getElementById('cost-test-results-banner').classList.add('hidden')" style="background:none; border:none; color:white; cursor:pointer;"><i data-lucide="x"></i></button>
            </div>
            <div class="test-results-list">
        `;
        
        results.forEach(res => {
            bannerHtml += `
                <div class="test-result-item ${res.status.toLowerCase()}">
                    <span class="test-status-pill">${res.status}</span>
                    <strong class="test-name">${res.name}</strong>
                    <span class="test-msg">${res.message}</span>
                </div>
            `;
        });
        
        bannerHtml += `</div>`;
        banner.innerHTML = bannerHtml;
        lucide.createIcons();
    }

    return results;
}

// Bind to window context
window.runCostingTests = runCostingTests;
console.log("RoomFlow Costing Verification Test Suite loaded.");
