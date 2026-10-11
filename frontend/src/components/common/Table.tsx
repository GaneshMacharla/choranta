import React from 'react';

export interface Column<T> {
  key: string;
  header: string;
  render?: (item: T) => React.ReactNode;
  className?: string;
}

interface TableProps<T> {
  columns: Column<T>[];
  data: T[];
  keyExtractor: (item: T) => string;
  onRowClick?: (item: T) => void;
  emptyState?: React.ReactNode;
}

export function Table<T>({
  columns,
  data,
  keyExtractor,
  onRowClick,
  emptyState,
}: TableProps<T>) {
  if (data.length === 0 && emptyState) {
    return <div className="p-8">{emptyState}</div>;
  }

  return (
    <div className="w-full overflow-x-auto">
      <table className="w-full text-left text-sm text-slate-300">
        <thead className="border-b border-[#102d38] bg-[#06161d] text-xs uppercase tracking-wider text-slate-400">
          <tr>
            {columns.map((col) => (
              <th key={col.key} scope="col" className={`px-5 py-3 font-medium ${col.className || ''}`}>
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-[#102d38]">
          {data.map((item) => (
            <tr
              key={keyExtractor(item)}
              onClick={() => onRowClick && onRowClick(item)}
              className={`
                group transition-colors duration-150
                ${onRowClick ? 'cursor-pointer hover:bg-[#0c242e]' : 'hover:bg-[#091f27]'}
              `}
            >
              {columns.map((col) => (
                <td key={col.key} className={`px-5 py-3.5 whitespace-nowrap ${col.className || ''}`}>
                  {col.render ? col.render(item) : (item as any)[col.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
