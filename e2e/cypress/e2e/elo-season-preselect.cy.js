describe("Elo showcase: Season preselection", () => {
  beforeEach(() => {
    // Load Elo page without query params so default preselection applies
    cy.visit("/elo.html");
    // Wait for Elo JSON to load + UI to render
    cy.get("#rankTable", { timeout: 10000 }).should("exist");
  });

  it("GIVEN Elo page loads WHEN no season query params provided THEN all visible seasons are preselected as active buttons", () => {
    // Get all season filter buttons
    cy.get("#seasonFilters .seasonBtn").then(($buttons) => {
      // GIVEN we have at least one season available
      expect($buttons.length).to.be.greaterThan(0);
    });

    // THEN verify all season buttons have the 'active' class (preselected)
    cy.get("#seasonFilters .seasonBtn")
      .should("have.class", "active")
      .each(($btn) => {
        const text = $btn.text();
        expect(text).match(/\d{4}-\d{4}/, `Season button should show year range, got: "${text}"`);
      });
  });

  it("GIVEN all seasons are preselected WHEN user opens page THEN rank table populates with teams across all selected seasons", () => {
    // WHEN page loads with all seasons active
    // THEN the rank table should have data rows (excluding the header)
    cy.get("#rankTable .tr").not(".th")
      .should("have.length.greaterThan", 0)
      .first()
      .invoke("text")
      .then((text) => {
        // data row should include rank and Elo numeric values
        expect(text).to.match(/\d+/);
      });
  });

  it("GIVEN all seasons preselected WHEN chart renders THEN season boundary lines visible for multi-season view", () => {
    // Get number of active seasons
    cy.get("#seasonFilters .seasonBtn.active").then(($active) => {
      const activeCount = $active.length;

      if (activeCount > 1) {
        // Multi-season: should have season boundary lines in the chart
        cy.get("#chart .season-line, #chart .season-boundary").should(
          "have.length.greaterThan",
          0
        );
      }
    });
  });

  it("GIVEN Elo page loads THEN help trigger '?' is visible near Elo reference", () => {
    cy.get("#eloHelpToggle").should("be.visible").and("contain.text", "?");
  });

  it("GIVEN user clicks Elo help '?' WHEN popover opens THEN help content is visible", () => {
    cy.get("#eloHelpPopover").should("not.be.visible");
    cy.get("#eloHelpToggle").click();
    cy.get("#eloHelpPopover").should("be.visible");
    cy.get("#eloHelpPopover").should("contain.text", "What is Elo?");
    cy.get("#eloHelpPopover").should("contain.text", "Higher Elo means stronger recent performance");
  });

  it("GIVEN help popover is open WHEN user clicks anywhere ELSE THEN popover closes", () => {
    cy.get("#eloHelpToggle").click();
    cy.get("#eloHelpPopover").should("be.visible");
    cy.get("body").click(0, 0);
    cy.get("#eloHelpPopover").should("not.be.visible");
  });
});
