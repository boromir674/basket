// ***********************************************
// This example commands.js shows you how to
// create various custom commands and overwrite
// existing commands.
//
// For more comprehensive examples of custom
// commands please read more here:
// https://on.cypress.io/custom-commands
// ***********************************************
//
//
// -- This is a parent command --
// Cypress.Commands.add("login", (email, password) => { ... })
//
//
// -- This is a child command --
// Cypress.Commands.add("drag", { prevSubject: 'element'}, (subject, options) => { ... })
//
//
// -- This is a dual command --
// Cypress.Commands.add("dismiss", { prevSubject: 'optional'}, (subject, options) => { ... })
//
//
// -- This is will overwrite an existing command --
// Cypress.Commands.overwrite("visit", (originalFn, url, options) => { ... })


// Prevent Cypress from failing, in case of (some) uncaught App exceptions
Cypress.on("uncaught:exception", (err, runnable) => {
  // Case 1: Allow specific uncaght exceptions to happen
  // we expect a 3rd party library error with message 'list not defined'
  // and don't want to fail the test so we return false
  // if (err.message.includes('list not defined')) {
  //   return false
  // }

  // we still want to ensure there are no other unexpected
  // errors, so we let them fail the test

  // Case 2: Allow any uncaught exception to happen
  // continue test(s) ingoring any uncaught exception
  return false;
});

// chrome reports computed font-family with quotes, firefox without
Cypress.Commands.add('shouldHaveFontFamily',
  {
    prevSubject: true,
  },
  (subject, expectedFont) => {
  cy.wrap(subject).should('satisfy', ($el) => {
    const actualFont = $el.css('font-family');
    // Normalize both by removing all quotes
    const normalizedActual = actualFont.replace(/["']/g, '');
    const normalizedExpected = expectedFont.replace(/["']/g, '');
    return normalizedActual === normalizedExpected;
  });
});
