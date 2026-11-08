import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { CampaignStory } from './CampaignStory';
import { InstantOutboundStory } from './InstantOutboundStory';

describe('feature stories', () => {
  it('steps through every campaign scene and wraps back to the start', () => {
    render(<CampaignStory />);
    fireEvent.click(screen.getByRole('button', { name: 'Pause' }));
    const titles = [
      'You upload your list',
      'You choose when it calls',
      'Your AI employee works through the list',
      'Anyone it missed gets another try',
      'You see how it went',
    ];
    for (const title of titles) {
      expect(screen.getByRole('heading', { name: title })).toBeTruthy();
      fireEvent.click(screen.getByRole('button', { name: 'Next step' }));
    }
    expect(screen.getByRole('heading', { name: titles[0] })).toBeTruthy();
  });

  it('jumps to a step from its progress bar', () => {
    render(<CampaignStory />);
    fireEvent.click(screen.getByRole('button', { name: 'Step 5: You see how it went' }));
    expect(screen.getByText('Step 5 of 5')).toBeTruthy();
  });

  it('still tells the instant outbound story', () => {
    render(<InstantOutboundStory />);
    expect(screen.getByRole('heading', { name: 'How Instant Outbound works' })).toBeTruthy();
    expect(screen.getByText('Step 1 of 4')).toBeTruthy();
  });
});
