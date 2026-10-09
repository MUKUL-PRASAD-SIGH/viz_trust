import Ambient from "../components/Ambient.jsx";
import { useEffect, useState } from "react";
import Footer from "../components/Footer.jsx";
import MicroLabel from "../components/MicroLabel.jsx";
import Nav from "../components/Nav.jsx";
import Reveal from "../components/Reveal.jsx";
import { DOCS_SECTIONS } from "../content/docs.js";

export default function Docs() {
  const [active, setActive] = useState(DOCS_SECTIONS[0].id);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.find((entry) => entry.isIntersecting);
        if (visible) setActive(visible.target.id);
      },
      { rootMargin: "-15% 0px -70% 0px" },
    );
    DOCS_SECTIONS.forEach(({ id }) => {
      const node = document.getElementById(id);
      if (node) observer.observe(node);
    });
    return () => observer.disconnect();
  }, []);

  return (
    <>
      <Ambient />
      <Nav />
      <main className="page">
        <section className="page-intro">
          <MicroLabel>Documentation</MicroLabel>
          <p className="display">
            Everything the <em>protocol</em> is, in one place.
          </p>
          <p className="display-sub">
            The reader-facing summary of SPEC.md and README.md — the frozen type definitions and
            setup instructions remain the source of truth in the repository.
          </p>
        </section>

        <div className="section docs-layout">
          <nav className="docs-nav" aria-label="Documentation sections">
            {DOCS_SECTIONS.map((section) => (
              <a
                key={section.id}
                href={`#${section.id}`}
                className={active === section.id ? "active" : ""}
              >
                {section.title}
              </a>
            ))}
          </nav>

          <div className="docs-content">
            {DOCS_SECTIONS.map((section) => (
              <Reveal as="article" key={section.id} id={section.id} className="docs-section">
                <h2>{section.title}</h2>
                <div className="docs-section-body">
                  {section.body.map((paragraph) => (
                    <p key={paragraph}>{paragraph}</p>
                  ))}
                  {section.table && (
                    <table className="docs-table">
                      <thead>
                        <tr>
                          {section.table.head.map((h) => (
                            <th key={h}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {section.table.rows.map((row) => (
                          <tr key={row[0]}>
                            {row.map((cell, i) => (
                              <td key={i}>{cell}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                  {section.note && <p className="muted-small">{section.note}</p>}
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </main>
      <Footer />
    </>
  );
}
