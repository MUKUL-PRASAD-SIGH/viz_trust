import Ambient from "../components/Ambient.jsx";
import { Link } from "react-router-dom";
import Footer from "../components/Footer.jsx";
import MicroLabel from "../components/MicroLabel.jsx";
import Nav from "../components/Nav.jsx";

export default function NotFound() {
  return (
    <>
      <Ambient />
      <Nav />
      <main className="page">
        <section className="page-intro">
          <MicroLabel>404</MicroLabel>
          <p className="display">
            No <em>record</em> at this address.
          </p>
          <p className="display-sub">
            The page you asked for doesn't exist. Every agent here has a history — this URL doesn't.
          </p>
          <Link to="/" className="text-link">
            Back to overview →
          </Link>
        </section>
      </main>
      <Footer />
    </>
  );
}
