# frozen_string_literal: true

# SkyWatch's tests, run with `trmnlp test` from plugin/ (add `--report report` for a page of every screen).
# The polling url answers with tests/fixtures/skywatch.json: a real sample over Belgium plus a climbing, a
# descending, a ground and a 7700 aircraft. No network. Docs: https://github.com/usetrmnl/trmnlp#testing-plugins
require 'fileutils'
require 'json'
require 'tmpdir'

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

  # ---- Cross-section view ---------------------------------------------------------------------------------------
  # No map in this mode, so the pixels are stable and compared (tests/snapshots/<os>/xsection-*.png). The test
  # browser draws the plugin dark (settings.yml dark_mode: yes), so the light variant renders a copy of the plugin
  # with that switched off.
  let(:xs_fields) { custom_fields.merge('view' => 'xsection', 'xs_axis' => 'distance', 'xs_heading' => '90') }

  def xs_screen(fields, view: 'full', light: false)
    return trmnl.render(view:, mocks:, custom_fields: fields) unless light

    Dir.mktmpdir do |dir|
      FileUtils.cp_r([File.join(Dir.pwd, 'src'), File.join(Dir.pwd, '.trmnlp.yml')], dir)
      %w[src/settings.yml .trmnlp.yml].each do |f|
        path = File.join(dir, f)
        File.write(path, File.read(path).sub("dark_mode: 'yes'", "dark_mode: 'no'"))
      end
      trmnl.plugin(dir).render(view:, mocks:, custom_fields: fields)
    end
  end

  def drawn(screen) = screen.all('[data-xs-plane]', visible: :all).map { it['data-xs-plane'] }
  def tagged(screen) = screen.all('[data-xs-tag]', visible: :all).map { it['data-xs-tag'] }

  { 'distance' => {}, 'eastwest' => {}, 'heading' => { 'xs_heading' => '90' } }.each do |axis, extra|
    [false, true].each do |light|
      it "draws the cross-section (#{axis}, #{light ? 'light' : 'dark'})" do
        screen = xs_screen(xs_fields.merge('xs_axis' => axis).merge(extra), light:)
        expect(screen.problems).to be_empty
        expect(screen).to match_snapshot("xsection-#{axis}-#{light ? 'light' : 'dark'}")
      end
    end
  end

  it 'draws and tags the 7700 aircraft' do
    screen = xs_screen(xs_fields)
    expect(drawn(screen)).to include('DLH4AB')
    expect(tagged(screen)).to include('DLH4AB')
    expect(screen).to have_text('MAYDAY')
  end

  # Every tag has its own dashed leader line, and no tag overlaps the provider label or another tag.
  TAG_GEOMETRY_JS = <<~JS.freeze
    (function () {
      var rect = function (e) { var b = e.getBoundingClientRect(); return { l: b.left, t: b.top, r: b.right, b: b.bottom }; };
      var hit = function (a, b) { return a.l < b.r && a.r > b.l && a.t < b.b && a.b > b.t; };
      var tags = Array.prototype.slice.call(document.querySelectorAll('[data-xs-tag]'));
      var leaders = Array.prototype.slice.call(document.querySelectorAll('[data-xs-leader]')).map(function (l) { return l.getAttribute('data-xs-leader'); });
      var label = rect(document.querySelector('.layout[data-chart] .label'));
      var res = { tags: tags.length, noLeader: [], onLabel: [], overlap: [] };
      tags.forEach(function (t, i) {
        var n = t.getAttribute('data-xs-tag'), r = rect(t);
        if (leaders.indexOf(n) < 0) res.noLeader.push(n);
        if (hit(r, label)) res.onLabel.push(n);
        for (var j = i + 1; j < tags.length; j++) if (hit(r, rect(tags[j]))) res.overlap.push(n + '/' + tags[j].getAttribute('data-xs-tag'));
      });
      return res;
    })()
  JS

  %w[distance eastwest heading].each do |axis|
    it "gives every tag a leader line and keeps tags clear of the label and each other (#{axis})" do
      geo = xs_screen(xs_fields.merge('xs_axis' => axis)).evaluate(TAG_GEOMETRY_JS)
      expect(geo['tags']).to be >= 6
      expect(geo['noLeader']).to be_empty
      expect(geo['onLabel']).to be_empty
      expect(geo['overlap']).to be_empty
    end
  end

  it 'keeps every icon below the provider label' do
    screen = xs_screen(xs_fields)
    label_bottom = screen.evaluate("document.querySelector('.layout[data-chart] .label').getBoundingClientRect().bottom")
    tops = screen.evaluate("Array.prototype.map.call(document.querySelectorAll('[data-xs-plane] use'), function (u) { return u.getBoundingClientRect().top; })")
    expect(tops.min).to be >= label_bottom - 8   # the rotated icon's box is a little tighter than its 24 unit square
  end

  it 'turns ground aircraft to face left or right, level' do
    screen = xs_screen(xs_fields.merge('show_ground' => 'true'))
    rot = screen.evaluate("document.querySelector('[data-xs-ground] g').getAttribute('transform')")
    expect(rot).to match(/rotate\((90|-90)\)/)
  end

  it 'draws at most 12 aircraft' do
    screen = xs_screen(xs_fields)
    expect(drawn(screen).size).to be_between(1, 12)
  end

  it 'draws ground aircraft on the strip only with show_ground' do
    on = xs_screen(xs_fields.merge('show_ground' => 'true'))
    off = xs_screen(xs_fields.merge('show_ground' => 'false'))
    expect(on.all('[data-xs-ground]', visible: :all).size).to eq(1)
    expect(off.all('[data-xs-ground]', visible: :all).size).to eq(0)
  end

  it 'dims aircraft far from the heading line instead of dropping them' do
    screen = xs_screen(xs_fields.merge('xs_axis' => 'heading', 'xs_heading' => '90'))
    dimmed = screen.all('[data-xs-dim]', visible: :all).map { it['data-xs-plane'] }
    expect(dimmed).not_to be_empty
    expect(tagged(screen) & dimmed).to be_empty
    expect(dimmed).not_to include('DLH4AB')   # the 7700 aircraft is never dimmed
    expect(tagged(screen)).to include('DLH4AB')
  end

  %w[full half_horizontal half_vertical quadrant].each do |layout|
    next if layout == 'full'

    it "keeps the radar on the #{layout} layout when the cross-section is chosen" do
      page = trmnl.render(view: layout, mocks:, custom_fields: xs_fields).html.gsub(/inst_[A-Za-z0-9]+/, 'inst_X')
      expect(page).to eq(File.read(File.join(__dir__, 'snapshots', "radar-#{layout}.html")))
    end
  end
end
