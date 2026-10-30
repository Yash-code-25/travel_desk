// Travel Manager overview: the queue, this month, booking speed and each agent's workload.
import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { formatMoney } from '../utils.js'
import { Avatar } from './ui.jsx'

export default function DeskAnalytics({ refreshKey }) {
  const [data, setData] = useState(null)
  useEffect(() => { api('/desk/analytics/').then(setData).catch(() => {}) }, [refreshKey])
  if (!data) return null

  const month = new Date().toLocaleDateString('en-IN', { month: 'long' })
  const busiest = Math.max(1, ...data.agents.map((a) => a.in_progress))
  return (
    <section className="analytics">
      <div className="kpi-row">
        <Kpi label="Waiting to assign" value={data.waiting_assignment} alert={data.oldest_waiting_hours >= 24}
             hint={data.oldest_waiting_hours != null ? `oldest waiting ${waitText(data.oldest_waiting_hours)}` : 'everything is assigned'} />
        <Kpi label="Being booked" value={data.in_progress} hint={`${data.cancellation_requests} cancellation request${data.cancellation_requests === 1 ? '' : 's'}`} />
        <Kpi label={`Booked in ${month}`} value={data.month.trips_booked}
             hint={`${data.month.domestic} domestic · ${data.month.international} international`} />
        <Kpi label={`Spend in ${month}`} value={formatMoney(data.month.spend)}
             hint={data.avg_hours_to_book != null ? `avg. approval to booked: ${waitText(data.avg_hours_to_book)}` : 'no bookings in 30 days'} />
      </div>

      <div className="panel workload-panel">
        <p className="section-label workload-title mobile-only">Agent workload</p>
        <table className="workload">
          <thead>
            <tr><th>Agent workload</th><th className="num">Being booked</th><th className="num">Cancellations</th><th className="num">Booked (30 days)</th></tr>
          </thead>
          <tbody>
            {data.agents.map((a) => (
              <tr key={a.id}>
                <td className="agent-cell">
                  <span className="person"><Avatar name={a.name} size={28} /><span><strong>{a.name}</strong><small className="subtle xs block">{a.role_label}</small></span></span>
                </td>
                <td className="num" data-label="Being booked">{a.in_progress}<span className="bar" style={{ width: `${(a.in_progress / busiest) * 48}px` }} /></td>
                <td className="num" data-label="Cancellations">{a.cancellations}</td>
                <td className="num" data-label="Booked (30d)">{a.booked_30d}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function Kpi({ label, value, hint, alert }) {
  return (
    <div className={`kpi ${alert ? 'alert' : ''}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {hint && <small>{hint}</small>}
    </div>
  )
}

/** 0.4 -> "under 1h", 5 -> "5h", 50 -> "2 days" */
function waitText(hours) {
  if (hours < 1) return 'under 1h'
  return hours < 48 ? `${Math.round(hours)}h` : `${Math.round(hours / 24)} days`
}
