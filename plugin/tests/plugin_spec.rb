# frozen_string_literal: true

# SkyWatch's tests, run with `trmnlp test` from plugin/ (add `--report report` for a page of every screen).
# The polling url answers with tests/fixtures/skywatch.json: a real sample over Belgium plus a climbing, a
# descending, a ground and a 7700 aircraft. No network. Docs: https://github.com/usetrmnl/trmnlp#testing-plugins
require 'fileutils'
require 'json'

RSpec.describe 'SkyWatch' do
  let(:fixture) { JSON.parse(File.read(File.join(__dir__, 'fixtures', 'skywatch.json'))) }
  let(:mocks) { { 'https://trmnl.bettens.dev/skywatch*' => { json: fixture } } }
  let(:custom_fields) { { 'address' => 'Sint-Lodewijk', 'unit' => 'imperial', 'show_ground' => 'true' } }

  # Every view on TRMNL's devices, a failing API and every select option: no page errors, no leaked values.
  it_behaves_like 'a publishable recipe'

  # The radar as it is: the page each layout sends to the device, compared byte for byte with the one recorded
  # before the cross-section view was added (tests/snapshots/radar-*.html). With the view setting at its default
  # it must not change. Only the per-render random instance id is normalised. (Pixels cannot be compared here:
  # the test browser has no WebGL, so MapLibre draws nothing.) Record again only on purpose: RECORD=1 trmnlp test
  def radar_page(layout, **opts)
    trmnl.render(view: layout, mocks:, custom_fields:, **opts).html.gsub(/inst_[A-Za-z0-9]+/, 'inst_X')
  end

  def match_recorded(name, page)
    path = File.join(__dir__, 'snapshots', "#{name}.html")
    if ENV['RECORD'] == '1' || !File.exist?(path)
      FileUtils.mkdir_p(File.dirname(path))
      File.write(path, page)
    end
    expect(page).to eq(File.read(path)), "#{name}: the radar page differs from tests/snapshots/#{name}.html"
  end

  %w[full half_horizontal half_vertical quadrant].each do |layout|
    it "sends the radar page unchanged (#{layout})" do
      match_recorded("radar-#{layout}", radar_page(layout))
    end
  end

  it 'sends the radar page unchanged in dark mode (full)' do
    match_recorded('radar-full-dark', radar_page('full', dark_mode: true))
  end
end
