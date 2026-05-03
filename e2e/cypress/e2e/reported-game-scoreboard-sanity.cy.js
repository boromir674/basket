describe("Game Viewer reported-game sanity", () => {
  const getViewerBody = () => {
    return cy
      .get("#viewer", { timeout: 20000 })
      .its("0.contentDocument.body")
      .should("not.be.empty")
      .then(cy.wrap);
  };

  it("GIVEN fixture expectations WHEN user finds reported game via UI THEN scoreboard names, scores, and pregame ELO match", () => {
    cy.fixture("reported-game-e2025-375.json").then((expected) => {
      // GIVEN the game discovery page is loaded
      cy.visit("/");

      // Wait until game list is populated
      cy.get("#games .game-row", { timeout: 20000 }).should("have.length.greaterThan", 0);

      // WHEN user filters by season and searches by exact matchup/date
      cy.get("#seasonFilter").select(expected.seasoncode);
      cy.get("#searchFilter")
        .clear()
        .type(`${expected.gamedate} ${expected.team_a} ${expected.team_b}`);

      // Select the exact game from visible rows
      cy.get("#games .game-row")
        .contains(`${expected.seasoncode} / ${expected.gamecode}`)
        .click();

      // Ensure parent context also reflects expected game
      cy.get("#gameMeta").should("contain.text", `${expected.seasoncode} / ${expected.gamecode}`);
      cy.get("#gameMeta").should("contain.text", `${expected.team_a} vs ${expected.team_b}`);

      // THEN inside the viewer iframe, validate title + scoreboard ordering and values
      getViewerBody().within(() => {
        cy.get("#page-title", { timeout: 20000 }).should(
          "have.text",
          `${expected.team_a} vs ${expected.team_b}`
        );

        // Guard against the reported regression shape where winner/score placement gets inverted.
        const expectedPrimary = `${expected.score_a} — ${expected.score_b}`;
        const reversedPrimary = `${expected.score_b} — ${expected.score_a}`;

        cy.get("#scoreboard .scoreboard-primary", { timeout: 20000 }).should(
          "have.text",
          expectedPrimary
        );

        cy.get("#scoreboard .scoreboard-primary", { timeout: 20000 })
          .invoke("text")
          .then((primaryText) => {
            expect(primaryText.trim(), "scoreline must not be reversed").to.not.equal(
              reversedPrimary
            );
          });

        // Winner must match the larger score according to fixture truth.
        const expectedWinner =
          expected.score_a > expected.score_b ? expected.team_a : expected.team_b;
        expect(expected.winner).to.equal(expectedWinner);

        const roundedPregameA = Math.round(expected.elo_a_before);
        const roundedPregameB = Math.round(expected.elo_b_before);
        const roundedDisplayA = Math.round(expected.elo_a_display);
        const roundedDisplayB = Math.round(expected.elo_b_display);

        const allowedEloLines = [
          `Pregame ELO: ${expected.team_a} ${roundedPregameA} · ${expected.team_b} ${roundedPregameB}`,
          `ELO: ${expected.team_a} ${roundedDisplayA} · ${expected.team_b} ${roundedDisplayB}`,
        ];

        cy.get("#scoreboard .scoreboard-secondary", { timeout: 20000 })
          .invoke("text")
          .then((actualText) => {
            expect(allowedEloLines).to.include(actualText.trim());
          });
      });
    });
  });

  it("GIVEN anchor scope on away winner WHEN loading reported game THEN home/away title and score order stay aligned", () => {
    cy.fixture("reported-game-e2025-375.json").then((expected) => {
      cy.visit("/");

      cy.get("#games .game-row", { timeout: 20000 }).should("have.length.greaterThan", 0);

      // Reproduce the user's flow: anchor mode + anchored away winner team.
      cy.get("#scope-anchor").click();
      cy.get("#teamSelect").select(expected.team_b);

      cy.get("#seasonFilter").select(expected.seasoncode);
      cy.get("#searchFilter")
        .clear()
        .type(`${expected.gamedate} ${expected.team_a} ${expected.team_b}`);

      cy.get("#games .game-row")
        .contains(`${expected.seasoncode} / ${expected.gamecode}`)
        .click();

      getViewerBody().within(() => {
        // Title stays in canonical Home vs Away ordering.
        cy.get("#page-title", { timeout: 20000 }).should(
          "have.text",
          `${expected.team_a} vs ${expected.team_b}`
        );

        // Scoreboard must remain aligned to title ordering (team_a first, team_b second).
        // Current bug under anchor mode can invert this to 85 — 76.
        cy.get("#scoreboard .scoreboard-primary", { timeout: 20000 }).should(
          "have.text",
          `${expected.score_a} — ${expected.score_b}`
        );
      });
    });
  });
});
