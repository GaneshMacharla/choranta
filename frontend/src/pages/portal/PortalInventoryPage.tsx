import React, { useEffect, useState } from 'react';
import { Card } from '../../components/common/Card';
import { LoadingState } from '../../components/common/LoadingState';
import { ErrorState } from '../../components/common/ErrorState';
import { portalService } from '../../services/portal';

type Inventory = Awaited<ReturnType<typeof portalService.properties>>;

export const PortalInventoryPage: React.FC = () => {
  const [data, setData] = useState<Inventory | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    portalService.properties().then(setData).catch((err) => setError(err.message || 'Could not load properties.'));
  }, []);

  if (error) return <ErrorState message={error} onRetry={() => window.location.reload()} />;
  if (!data) return <LoadingState message="Loading properties..." />;

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div>
        <h1 className="text-xl font-bold">Properties</h1>
        <p className="text-xs text-slate-400">
          What your AI employee can offer callers ({data.count} listings
          {data.last_synced_at ? `, synced ${new Date(data.last_synced_at).toLocaleString('en-IN')}` : ''}). Update your sheet or CRM;
          changes sync automatically.
        </p>
      </div>
      <Card noPadding>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-[#1f2433] text-slate-400">
              <tr>
                <th className="px-4 py-3">Project</th>
                <th className="px-4 py-3">Location</th>
                <th className="px-4 py-3">BHK</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Price</th>
                <th className="px-4 py-3">Status</th>
              </tr>
            </thead>
            <tbody>
              {data.properties.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-slate-500">No properties synced yet.</td>
                </tr>
              )}
              {data.properties.map((p) => (
                <tr key={p.id} className="border-b border-[#151a26] text-slate-300">
                  <td className="px-4 py-3">{p.project_name}</td>
                  <td className="px-4 py-3">{p.location}</td>
                  <td className="px-4 py-3">{p.bhk || '—'}</td>
                  <td className="px-4 py-3">{p.property_type}</td>
                  <td className="px-4 py-3 font-mono">{p.price_display}</td>
                  <td className="px-4 py-3">{p.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
};
