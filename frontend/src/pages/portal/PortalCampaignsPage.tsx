import React from 'react';
import { CampaignDetail, CampaignsList } from '../../components/campaigns/CampaignViews';
import { CampaignStory } from '../../components/portal/CampaignStory';
import { InstantOutboundStory } from '../../components/portal/InstantOutboundStory';

export const PortalCampaignsPage: React.FC = () => (
  <div className="mx-auto max-w-6xl space-y-6">
    <CampaignStory />
    <CampaignsList scope="portal" basePath="/portal/campaigns" />
  </div>
);

export const PortalCampaignDetailPage: React.FC = () => (
  <div className="mx-auto max-w-6xl">
    <CampaignDetail scope="portal" basePath="/portal/campaigns" />
  </div>
);

export const PortalInstantOutboundPage: React.FC = () => (
  <div className="mx-auto max-w-6xl space-y-6">
    <InstantOutboundStory />
    <CampaignsList scope="portal" basePath="/portal/instant-outbound" kind="TRIGGER" />
  </div>
);

export const PortalInstantOutboundDetailPage: React.FC = () => (
  <div className="mx-auto max-w-6xl">
    <CampaignDetail scope="portal" basePath="/portal/instant-outbound" />
  </div>
);
