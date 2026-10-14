# frozen_string_literal: true

# SkyWatch's tests, run with `trmnlp test` from plugin/ (add `--report report` for a page of every screen).
# The polling url answers with tests/fixtures/skywatch.json: a real sample over Belgium plus a climbing, a
# descending, a ground and a 7700 aircraft. No network. Docs: https://github.com/usetrmnl/trmnlp#testing-plugins
require 'fileutils'
require 'json'
require 'tmpdir'
require 'yaml'

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

  # ---- Closest aircraft panel -----------------------------------------------------------------------------------
  # Off by default: the radar guard and the cross-section snapshots above cover "nothing changes". The radar draws
  # no pixels here (no WebGL) but the panel is plain HTML, so its text is asserted; the cross-section is compared
  # as pixels. The fixture's closest airborne aircraft is RYR8CL (5.5 nm, climbing); fetched_at is 20:16 UTC and the
  # test user's offset makes that 8:16 PM.
  let(:cd_fields) { custom_fields.merge('closest_details' => 'true') }

  def only(*flights, **change)
    data = JSON.parse(File.read(File.join(__dir__, 'fixtures', 'skywatch.json')))
    data['data']['ac'] = data['data']['ac'].select { flights.include?(it['flight']) }.map { |a| a.merge(change.transform_keys(&:to_s)) }
    { 'https://trmnl.bettens.dev/skywatch*' => { json: data } }
  end

  def panel(fields, view: 'full', mocks: self.mocks)
    trmnl.render(view:, mocks:, custom_fields: fields).then do |screen|
      screen.has_css?('[data-closest-panel]', visible: :all) ? screen.find('[data-closest-panel]', visible: :all).text(:all).strip : nil
    end
  end

  it 'shows no panel by default, in either view' do
    expect(panel(custom_fields)).to be_nil
    expect(panel(custom_fields.merge('view' => 'xsection'))).to be_nil
  end

  %w[radar xsection].each do |mode|
    it "shows the closest airborne aircraft in the #{mode} view" do
      text = panel(cd_fields.merge('view' => mode))
      expect(text).to include('RYR8CL', 'Boeing 737-800', '6200 ft', '248 kt', '1800 fpm', '5.5 nm NW', 'CRL', 'BCN', 'Climbing', 'EI-DHS')
    end
  end

  it 'shows metres, km, km/h and m/s in metric' do
    text = panel(cd_fields.merge('unit' => 'metric'))
    expect(text).to include('1890 m', '459 km/h', '9.1 m/s', '10.1 km', '74.1 km to go')
    expect(text).not_to include(' ft', ' kt', ' nm', 'fpm')
    expect(text).to include('ETA 20:26')
  end

  it 'picks a ground aircraft only when nothing is airborne' do
    expect(panel(cd_fields, mocks: only('', 'RYR8CL'))).to include('RYR8CL')
    text = panel(cd_fields, mocks: only(''))
    expect(text).to include('GND', 'On the ground')
  end

  it 'names the flight phase' do
    expect(panel(cd_fields, mocks: only('RYR8CL'))).to include('Climbing')
    expect(panel(cd_fields, mocks: only('DLH4AB'))).to include('Descending')
    expect(panel(cd_fields, mocks: only('BEL7MZ'))).to include('Approach')
    expect(panel(cd_fields, mocks: only('BEL7MZ', progress: 0.2))).to include('Approach')   # near the destination, not far along
    expect(panel(cd_fields, mocks: only('BEL7MZ', progress: 0.2, dest_dist_nm: 80))).to include('Descending')
    expect(panel(cd_fields, mocks: only('RYR8CL', alt_baro: 1500))).to include('Taking off')
    expect(panel(cd_fields, mocks: only('IBE0603'))).to include('Cruising')
  end

  it 'shows the distance left and the ETA from fetched_at, only above 50 kt' do
    text = panel(cd_fields, mocks: only('BEL7MZ'))
    expect(text).to include('30 nm to go', 'ETA 8:26 PM')   # 30 nm at 180 kt is 10 minutes after 8:16 PM
    slow = panel(cd_fields, mocks: only('BEL7MZ', gs: 40))
    expect(slow).to include('30 nm to go')
    expect(slow).not_to include('ETA')
  end

  it 'flags an emergency squawk at the top of the panel' do
    expect(panel(cd_fields, mocks: only('DLH4AB'))).to start_with('MAYDAY')
  end

  it 'ignores the setting on the smaller layouts' do
    %w[half_horizontal half_vertical quadrant].each do |layout|
      page = trmnl.render(view: layout, mocks:, custom_fields: cd_fields).html.gsub(/inst_[A-Za-z0-9]+/, 'inst_X')
      expect(page).to eq(File.read(File.join(__dir__, 'snapshots', "radar-#{layout}.html")))
    end
  end

  [false, true].each do |light|
    it "draws the panel in the cross-section (#{light ? 'light' : 'dark'})" do
      screen = xs_screen(xs_fields.merge('closest_details' => 'true'), light:)
      expect(screen.problems).to be_empty
      expect(screen).to match_snapshot("xsection-closest-#{light ? 'light' : 'dark'}")
    end
  end

  it 'marks the closest aircraft on the chart and keeps tags off the panel' do
    screen = xs_screen(xs_fields.merge('closest_details' => 'true'))
    expect(screen.all('[data-closest-marker]', visible: :all).size).to eq(1)
    hit = screen.evaluate(<<~JS)
      (function () {
        var p = document.querySelector('[data-closest-panel]').getBoundingClientRect();
        return Array.prototype.some.call(document.querySelectorAll('[data-xs-tag]'), function (t) {
          var b = t.getBoundingClientRect();
          return b.left < p.right && b.right > p.left && b.top < p.bottom && b.bottom > p.top;
        });
      })()
    JS
    expect(hit).to be(false)
  end

  # settings.yml: every conditional_validation names a value its field offers and fields that exist.
  it 'has consistent conditional custom fields' do
    fields = YAML.safe_load_file(File.join(__dir__, '..', 'src', 'settings.yml'))['custom_fields']
    by_key = fields.to_h { [it['keyname'], it] }
    conditions = fields.select { it['conditional_validation'] }
    expect(conditions).not_to be_empty
    conditions.each do |field|
      offered = Array(field['options']).map { it.is_a?(Hash) ? it.values.first.to_s : it.to_s }
      field['conditional_validation'].each do |rule|
        expect(offered).to include(rule['when'].to_s), "#{field['keyname']}: no option #{rule['when'].inspect}"
        rule['hidden'].each { |k| expect(by_key).to have_key(k), "#{field['keyname']} hides unknown field #{k}" }
      end
    end
  end

  # A hidden field keeps its old value: the heading is ignored unless the axis is "heading".
  it 'ignores a stale heading when the axis is not heading' do
    a = xs_screen(xs_fields.merge('xs_axis' => 'eastwest', 'xs_heading' => '45')).evaluate("document.querySelector('[data-chart] svg').innerHTML.length")
    b = xs_screen(xs_fields.merge('xs_axis' => 'eastwest', 'xs_heading' => '200')).evaluate("document.querySelector('[data-chart] svg').innerHTML.length")
    expect(a).to eq(b)
  end
end
