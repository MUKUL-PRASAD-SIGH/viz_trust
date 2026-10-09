// SPEC.md section 3. Static reference table for the landing page.
const ROWS = [
  ["Excellent", "800-1000", "20%", "$100"],
  ["Good", "600-799", "40%", "$200"],
  ["Fair", "400-599", "70%", "$350"],
  ["Poor", "0-399", "100%", "$500"],
];

export default function CollateralTable() {
  return (
    <div className="table-wrap">
      <table className="catalog-table">
        <thead>
          <tr>
            <th>Band</th>
            <th>Score</th>
            <th>Deposit</th>
            <th className="num">On a $500 job</th>
          </tr>
        </thead>
        <tbody>
          {ROWS.map(([band, range, pct, dollars]) => (
            <tr key={band}>
              <td>{band}</td>
              <td>{range}</td>
              <td>{pct}</td>
              <td className="num">{dollars}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="table-foot">Quoted on the hirer's score at job creation.</div>
    </div>
  );
}
