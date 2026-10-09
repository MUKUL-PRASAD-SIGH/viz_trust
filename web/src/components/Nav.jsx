import { Link, NavLink } from "react-router-dom";

// `status` replaces the Open Dashboard button on /dashboard, where it would link to itself.
export default function Nav({ status }) {
  return (
    <nav className="nav">
      <div className="nav-inner">
        <Link to="/" className="nav-brand">
          AEGIS
        </Link>
        <div className="nav-links">
          <NavLink to="/" end>
            Overview
          </NavLink>
          <NavLink to="/how-it-works">How it works</NavLink>
          <NavLink to="/docs">Docs</NavLink>
        </div>
        <div className="nav-right">
          {status ?? (
            <Link to="/dashboard" className="button-accent">
              Open Dashboard
            </Link>
          )}
        </div>
      </div>
    </nav>
  );
}
