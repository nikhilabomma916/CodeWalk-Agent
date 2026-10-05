// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { LandingPage } from "./landing-page";
import { LANDING_SECTIONS } from "./landing-config";

function renderLanding() {
  render(<LandingPage />);
  return screen.getByRole("navigation", { name: "Main" });
}

describe("Landing page", () => {
  it("has one h1 with the product statement and a heading per section", () => {
    renderLanding();
    const h1 = screen.getAllByRole("heading", { level: 1 });
    expect(h1).toHaveLength(1);
    expect(h1[0]).toHaveTextContent("Your Codebase.Understood by AI.");
    for (const name of [
      /One line of code/,
      /Connected parts of one system/,
      /Six steps/,
      /The project as a set of relationships/,
      /You decide what enters your code/,
      /Ask your project/,
      /One workspace for code, context, diagnostics, and AI/,
      /A layered architecture/,
      /Questions, answered precisely/,
      /Stop Debugging/,
    ]) {
      expect(screen.getByRole("heading", { level: 2, name })).toBeInTheDocument();
    }
  });

  it("links every call to action to a real application route", () => {
    const nav = renderLanding();
    expect(within(nav).getByRole("link", { name: "Sign In" })).toHaveAttribute("href", "/login");
    expect(within(nav).getByRole("link", { name: "Open Workspace" })).toHaveAttribute(
      "href",
      "/app/coding",
    );
    const main = screen.getByRole("main");
    expect(within(main).getAllByRole("link", { name: /Open Workspace/ })[0]).toHaveAttribute(
      "href",
      "/app/coding",
    );
    expect(within(main).getByRole("link", { name: /Open CodeWalk Agent/ })).toHaveAttribute(
      "href",
      "/app/coding",
    );
    expect(within(main).getByRole("link", { name: "Explore the Workspace" })).toHaveAttribute(
      "href",
      "/app/projects",
    );
  });

  it("navigates to sections that exist on the page", () => {
    const nav = renderLanding();
    for (const section of LANDING_SECTIONS) {
      const link = within(nav).getAllByRole("link", { name: section.label })[0];
      expect(link).toHaveAttribute("href", `#${section.id}`);
      expect(document.getElementById(section.id)).not.toBeNull();
    }
  });

  it("opens and closes the mobile menu accessibly", async () => {
    renderLanding();
    const toggle = screen.getByRole("button", { name: "Open menu" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(document.getElementById("landing-menu")).not.toBeVisible();
    await userEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Close menu" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(document.getElementById("landing-menu")).toBeVisible();
    await userEvent.keyboard("{Escape}");
    expect(screen.getByRole("button", { name: "Open menu" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("answers an example question with the context it would retrieve", async () => {
    renderLanding();
    const group = screen.getByRole("group", { name: "Example questions" });
    await userEvent.click(within(group).getByRole("button", { name: "What changed recently?" }));
    expect(within(group).getByRole("button", { name: "What changed recently?" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText("project activity (last 7 days)")).toBeInTheDocument();
    expect(screen.getByText(/In CodeWalk, answers come from your own project/)).toBeInTheDocument();
  });

  it("explains a capability and a project relationship on selection", async () => {
    renderLanding();
    await userEvent.click(screen.getAllByRole("button", { name: "Reviewable Fixes" })[0]);
    expect(screen.getByRole("region", { name: "Reviewable Fixes details" })).toHaveTextContent(
      "Nothing is written until you approve",
    );

    await userEvent.click(screen.getByRole("button", { name: "models/user.py" }));
    expect(screen.getByText("Data model · __tablename__ users")).toBeInTheDocument();
    expect(screen.getByText("Example project relationship")).toBeInTheDocument();
  });

  it("uses an exclusive accordion for the FAQ, with the first answer open", () => {
    renderLanding();
    const faq = document.getElementById("faq")!;
    const items = faq.querySelectorAll("details");
    expect(items.length).toBe(8);
    expect([...items].every((d) => d.getAttribute("name") === "faq")).toBe(true);
    expect(items[0].open).toBe(true);
    expect(within(faq).getByText("Does AI automatically modify my code?")).toBeInTheDocument();
  });

  it("does not invent social proof or metrics", () => {
    renderLanding();
    const text = document.body.textContent ?? "";
    for (const claim of [
      /testimonial/i,
      /customers/i,
      /trusted by/i,
      /github stars/i,
      /\d+%/,
      /accuracy/i,
    ]) {
      expect(text).not.toMatch(claim);
    }
  });
});
