import React, { useMemo } from 'react';
import { GraduationCap } from 'lucide-react';
import { Card } from '../common/Card';
import { CourseCatalogue } from './CourseCatalogue';
import { clientCoursesService } from '../../services/courses';

/** Admin: a coaching client's course catalogue, with what the centre changed recently (fee changes highlighted). */
export const ClientCoursesCard: React.FC<{ clientId: string }> = ({ clientId }) => {
  const api = useMemo(() => clientCoursesService(clientId), [clientId]);
  return (
    <Card
      title={
        <span className="flex items-center gap-2 text-sm font-semibold text-slate-100">
          <GraduationCap className="h-4 w-4 text-[#00df8f]" /> Courses &amp; batches
        </span>
      }
      subtitle="The centre edits these in its portal too. Every AI employee of this client is given the whole catalogue on each call."
    >
      <CourseCatalogue api={api} showChanges />
    </Card>
  );
};
