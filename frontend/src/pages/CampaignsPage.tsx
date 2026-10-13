import React from 'react';
import { CampaignDetail, CampaignsList } from '../components/campaigns/CampaignViews';

export const CampaignsPage: React.FC = () => (
  <div className="mx-auto max-w-7xl p-8">
    <CampaignsList scope="admin" basePath="/campaigns" />
  </div>
);

export const CampaignDetailPage: React.FC = () => (
  <div className="mx-auto max-w-7xl p-8">
    <CampaignDetail scope="admin" basePath="/campaigns" />
  </div>
);

export const InstantOutboundPage: React.FC = () => (
  <div className="mx-auto max-w-7xl p-8">
    <CampaignsList scope="admin" basePath="/instant-outbound" kind="TRIGGER" />
  </div>
);

export const InstantOutboundDetailPage: React.FC = () => (
  <div className="mx-auto max-w-7xl p-8">
    <CampaignDetail scope="admin" basePath="/instant-outbound" />
  </div>
);
