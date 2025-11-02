import streamlit as st
import pandas as pd
import numpy as np
from collections import defaultdict
from itertools import combinations
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
import warnings

# Import SciPy dependencies
try:
    from scipy.special import comb
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    
warnings.filterwarnings('ignore')

# ============================================================================
# HELPER FUNCTIONS 
# ============================================================================

def calculate_triplets_weighted_stable(draws_list, weights_array):
    """Stable triplet calculation using Python dicts and weights."""
    triplets_weighted = defaultdict(float)
    for i, draw in enumerate(draws_list):
        weight = weights_array[i]
        for triplet in combinations(draw, 3):
            # Ensure triplet is always sorted for hashing
            triplets_weighted[tuple(sorted(triplet))] += weight
    return triplets_weighted

def calculate_lottery_probability(draw_count=12, total_numbers=66, match=4):
    """Calculate the exact probability of matching 'match' numbers dynamically."""
    if not SCIPY_AVAILABLE:
        # Fallback value (Problem 9 fix)
        return 0.00000316 
    
    try:
        # Use exact combination calculation
        numerator = comb(draw_count, match) * comb(total_numbers - draw_count, draw_count - match)
        denominator = comb(total_numbers, draw_count)
    except ValueError:
        return 0.00000316
    
    return numerator / denominator if denominator > 0 else 0.0

# ============================================================================
# LOTTERY ANALYZER
# ============================================================================
class LotteryAnalyzer:
    def __init__(self):
        self.draws = []
        self.frequency_weighted = defaultdict(float)
        self.triplets_weighted = defaultdict(float)
        self.gaps = defaultdict(int)
        self.markov_probabilities = defaultdict(lambda: defaultdict(float))
        self.ml_probs_array = np.zeros(67, dtype=np.float64)
        self.sum_mu = 0
        self.sum_sigma = 0

    def load_and_analyze(self, file_content):
        """Main entry point for loading and analysis."""
        self.draws = []
        lines = file_content.strip().split('\n')
        for line in lines:
            if not line.strip(): continue
            line = line.strip().replace(',', ' ')
            parts = [p.strip() for p in line.split() if p.strip()]
            
            if len(parts) >= 12:
                try:
                    start_index = 1 if len(parts) >= 13 and parts[0].isdigit() else 0 
                    numbers = [int(parts[i]) for i in range(start_index, start_index + 12)]
                    
                    if all(1 <= n <= 66 for n in numbers) and len(set(numbers)) == 12:
                        self.draws.append(sorted(numbers))
                except (ValueError, IndexError):
                    continue

        if len(self.draws) > 5000:
            self.draws = self.draws[-5000:]
            
        if self.draws:
            self._analyze_v7()

    def _analyze_v7(self):
        """v7 analysis with focus on triplets"""
        n = len(self.draws)
        if n < 10:
            st.session_state.warnings.append(f"AVERTISMENT: Doar {n} extrageri - analiza limitata.")
        
        weights = np.exp(np.linspace(-2, 0, n))
        weights = weights / np.sum(weights)

        # Weighted frequency 
        self.frequency_weighted = defaultdict(float)
        for i, draw in enumerate(self.draws):
            for num in draw:
                self.frequency_weighted[num] += weights[i]
        
        # Weighted triplets 
        recent_draws = self.draws[-2000:] if len(self.draws) > 2000 else self.draws
        recent_n = len(recent_draws)
        recent_weights = np.exp(np.linspace(-2, 0, recent_n))
        recent_weights = recent_weights / np.sum(recent_weights)

        self.triplets_weighted = calculate_triplets_weighted_stable(recent_draws, recent_weights)
        
        # Gaps, Markov, Sums, ML Probs
        for num in range(1, 67):
            for i in range(len(self.draws) - 1, -1, -1):
                if num in self.draws[i]:
                    self.gaps[num] = len(self.draws) - 1 - i
                    break
            if num not in self.gaps: self.gaps[num] = len(self.draws)
            self.ml_probs_array[num] = self.frequency_weighted.get(num, 0.0)
            
        # Markov
        markov_counts = defaultdict(lambda: defaultdict(float))
        for i in range(len(self.draws) - 1):
            weight = weights[i]
            for num1 in self.draws[i]:
                for num2 in self.draws[i + 1]:
                    markov_counts[num1][num2] += weight
        for num1 in markov_counts:
            total = sum(markov_counts[num1].values())
            if total > 0:
                for num2 in markov_counts[num1]:
                    self.markov_probabilities[num1][num2] = markov_counts[num1][num2] / total
                    
        # Sums
        sums = [sum(draw) for draw in self.draws]
        self.sum_mu = np.mean(sums)
        self.sum_sigma = np.std(sums)
            
        max_prob = np.max(self.ml_probs_array[1:])
        if max_prob > 0: self.ml_probs_array[1:] /= max_prob

    def extract_all_triplets_from_draws(self, min_support=0.01):
        """Extract top triplets from draws"""
        top_triplets = []
        min_weight_threshold = min_support * len(self.draws) 

        for triplet, weight in sorted(self.triplets_weighted.items(), key=lambda x: x[1], reverse=True):
            if weight >= min_weight_threshold: 
                top_triplets.append((list(triplet), weight))
            if len(top_triplets) >= 5000:
                break
        return top_triplets
    
    def get_candidate_score(self, triplet, num):
        """Calculates a normalized score for a single candidate number."""
        triplet_set = set(triplet)
        if num in triplet_set:
            return -999999
            
        # Normalization factors
        max_markov = 1.0 
        max_ml = 1.0
        max_freq = max(self.frequency_weighted.values()) if self.frequency_weighted else 1.0
        max_gap = max(self.gaps.values()) if self.gaps else 1.0
        
        # Normalized Markov score
        last_num = triplet[-1]
        markov_score = self.markov_probabilities[last_num].get(num, 0.0) / max(max_markov, 0.01) * 10
        
        # ML probability score (Weighted Frequency)
        ml_score = self.ml_probs_array[num] / max(max_ml, 0.01) * 15
        
        # Gap score (Penalty: closer to 0 is better)
        gap_score = self.gaps.get(num, len(self.draws)) / max(max_gap, 0.01)
        gap_penalty = gap_score * -5 
        
        # Frequency score (Weighted Frequency)
        freq_score = self.frequency_weighted.get(num, 0.0) / max(max_freq, 0.01) * 5
        
        return markov_score + ml_score + gap_penalty + freq_score

    def get_complementary_number(self, triplet):
        """Get top 5 candidate numbers to complete quad."""
        candidates = []
        for num in range(1, 67):
            score = self.get_candidate_score(triplet, num)
            if score > -999999: 
                candidates.append((num, score))
                
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[:5]

# ============================================================================
# TRIPLET EXTRACTOR
# ============================================================================
class TripletExtractor:
    def __init__(self, analyzer):
        self.analyzer = analyzer

    def _extract_from_variants_batch(self, variants_batch):
        """Extract triplets from variant batch"""
        triplet_scores = defaultdict(float)
        for variant in variants_batch:
            if len(variant) >= 3:
                for triplet in combinations(variant, 3):
                    triplet_tuple = tuple(sorted(triplet))
                    base_score = self.analyzer.triplets_weighted.get(triplet_tuple, 0.0)
                    freq_score = sum(self.analyzer.frequency_weighted.get(n, 0.0) for n in triplet) / 3.0
                    triplet_scores[triplet_tuple] += base_score * 2.0 + freq_score * 0.5 
        return triplet_scores

    def _extract_from_variants(self, variants):
        """Extract triplets from variant list with parallel processing"""
        if not variants: return {}
        num_workers = min(4, multiprocessing.cpu_count())
        batch_size = max(1000, len(variants) // num_workers)
        batches = [variants[i:i+batch_size] for i in range(0, len(variants), batch_size)]
        triplet_scores = defaultdict(float)
        try:
            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                futures = [executor.submit(self._extract_from_variants_batch, batch) for batch in batches]
                for future in futures:
                    batch_scores = future.result(timeout=60)
                    for triplet, score in batch_scores.items():
                        triplet_scores[triplet] += score
        except Exception as e:
            st.session_state.warnings.append(f"AVERTISMENT: Eroare ThreadPool, fallback la serial: {e}")
            for batch in batches:
                batch_scores = self._extract_from_variants_batch(batch)
                for triplet, score in batch_scores.items():
                    triplet_scores[triplet] += score
        return triplet_scores

    # V7.1: Fara logica de overlap
    def extract_top_triplets(self, pool_variants=None, top_n=2000):
        """Extract top N triplets from draws or pool based purely on score."""
        if pool_variants is None:
            triplets = self.analyzer.extract_all_triplets_from_draws()
        else:
            triplet_scores = self._extract_from_variants(pool_variants)
            # Sort all triplets found and convert to desired format
            triplets = [(list(t), s) for t, s in sorted(triplet_scores.items(), key=lambda x: x[1], reverse=True)]

        return triplets[:top_n]

# ============================================================================
# QUAD EXTENDER
# ============================================================================
class QuadExtender:
    def __init__(self, analyzer):
        self.analyzer = analyzer
        self.num_workers = min(4, multiprocessing.cpu_count())

    def _score_candidate_batch(self, batch_data):
        """Batch function for scoring and selecting best candidate for a set of triplets."""
        results = []
        for triplet, triplet_score in batch_data:
            candidates = self.analyzer.get_complementary_number(triplet)
            best_num = None
            best_score = -999999
            
            for num, num_score in candidates:
                total_score = triplet_score * 0.5 + num_score
                
                if total_score > best_score:
                    best_score = total_score
                    best_num = num
            
            results.append((best_num, best_score))
        return results

    # V7.1: Fara logica de overlap
    def generate_quads_from_triplets(self, triplets, num_variante=500):
        """Generate 4/4 quads from triplets based on score, enforcing only quad uniqueness."""
        quads = []
        seen_quads_sets = set() 
        
        target_triplets = triplets[:num_variante * 2] if len(triplets) > num_variante * 2 else triplets
        
        batch_data = []
        for triplet, triplet_score in target_triplets:
            batch_data.append((triplet, triplet_score))

        results = []
        try: 
            with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
                chunk_size = max(50, len(batch_data) // self.num_workers)
                chunks = [batch_data[i:i + chunk_size] for i in range(0, len(batch_data), chunk_size)]
                
                futures = [executor.submit(self._score_candidate_batch, chunk) for chunk in chunks]
                for future in futures:
                    results.extend(future.result(timeout=60))
        except Exception as e:
            st.session_state.warnings.append(f"AVERTISMENT: Eroare ThreadPool in QuadExtender, fallback la serial: {e}")
            results = self._score_candidate_batch(batch_data) # Serial fallback

        for i, ((triplet, _), (best_num, best_score)) in enumerate(zip(target_triplets, results)):
            if len(quads) >= num_variante:
                break

            if best_num is not None:
                quad = sorted(triplet + [best_num])
                quad_set = tuple(quad) 
                
                # Final check for uniqueness (must not be an exact duplicate of a previously generated quad)
                if quad_set not in seen_quads_sets:
                    quads.append((quad, best_score, triplet))
                    seen_quads_sets.add(quad_set)
        
        if len(quads) < num_variante:
            st.warning(f"Generat doar {len(quads)}/{num_variante} quad-uri unice (setul de triplete este epuizat).")

        return quads[:num_variante]

# ============================================================================
# COVERAGE OPTIMIZER
# ============================================================================
class CoverageOptimizer:
    def calculate_coverage(self, quads):
        """Calculate coverage statistics with improved score factoring."""
        
        if not quads:
            return {
                'covered_triplets': 0, 'triplet_coverage_percent': 0.0,
                'covered_quads': 0, 'quad_coverage_percent': 0.0,
                'estimated_win_chance': 0.0, 'avg_score': 0.0, 'max_score': 0.0
            }

        all_triplets = set()
        all_quads_set = set()
        scores = []
        
        for quad, score, _ in quads:
            all_quads_set.add(tuple(quad))
            for triplet in combinations(quad, 3):
                all_triplets.add(triplet)
            scores.append(score)
        
        # FIX V7.1 (Problema 3): Verificare pentru a evita np.mean/np.max pe liste goale
        avg_score = np.mean(scores) if scores else 0.0
        max_score = np.max(scores) if scores else 0.0
        max_score_theoretical = 50 

        total_possible_triplets = 45760  
        total_possible_quads = 73815  

        triplet_coverage = len(all_triplets) / total_possible_triplets * 100
        quad_coverage = len(all_quads_set) / total_possible_quads * 100

        single_quad_prob = calculate_lottery_probability(match=4) 
        num_quads = len(quads)
        win_chance = (1 - (1 - single_quad_prob) ** num_quads) * 100

        score_factor = avg_score / max_score_theoretical 
        
        coverage_base = min(1.0, (triplet_coverage + quad_coverage) / 20.0) 
        
        coverage_factor = coverage_base * (1 + score_factor * 0.2) 

        estimated_win = win_chance * min(coverage_factor, 1.5) 

        return {
            'covered_triplets': len(all_triplets),
            'triplet_coverage_percent': triplet_coverage,
            'covered_quads': len(all_quads_set),
            'quad_coverage_percent': quad_coverage,
            'estimated_win_chance': estimated_win,
            'avg_score': avg_score,
            'max_score': max_score
        }

# ============================================================================
# BACKTESTER
# ============================================================================
class Backtester:
    def __init__(self, analyzer):
        self.analyzer = analyzer

    def run_backtest(self, quads, num_draws=100):
        if not quads:
            return 0, 0, 0, 0
            
        test_draws = self.analyzer.draws[-num_draws:]
        quads_sets = [set(q) for q, _, _ in quads]
        
        total_hits = defaultdict(int) 
        
        for draw in test_draws:
            draw_set = set(draw)
            for quad_set in quads_sets:
                matches = len(draw_set.intersection(quad_set))
                if matches >= 2:
                    total_hits[matches] += 1
        
        avg_hits_2 = total_hits[2] / num_draws
        avg_hits_3 = total_hits[3] / num_draws
        avg_hits_4 = total_hits[4] / num_draws
        
        expected_hits = (avg_hits_2 * 2) + (avg_hits_3 * 3) + (avg_hits_4 * 4)
        
        return avg_hits_2, avg_hits_3, avg_hits_4, expected_hits

# ============================================================================
# UTILITIES (Direct Loading)
# ============================================================================
def handle_analysis_process(file_content):
    """V7.1: Function dedicata pentru a preveni 'Can't get local object' la initializare."""
    analyzer = LotteryAnalyzer()
    analyzer.load_and_analyze(file_content)
    return analyzer

# ============================================================================
# PAGE CONFIG & CSS
# ============================================================================
# V7.1 FIX: Foloseste doar caractere ASCII
st.set_page_config(page_title="Lottery Quad Builder v7.1", page_icon="o", layout="wide", initial_sidebar_state="expanded")

def apply_custom_css(dark_mode=False):
    if dark_mode:
        bg_color, text_color, card_bg = "#0E1117", "#FAFAFA", "#262730"
    else:
        bg_color, text_color, card_bg = "#FFFFFF", "#262730", "#F0F2F6"
    st.markdown(f"""
        <style>
        .stApp {{ background: linear-gradient(135deg, {bg_color} 0%, {card_bg} 100%); }}
        .main-header {{ text-align: center; padding: 20px; background: linear-gradient(90deg, #FF4B4B, #00D4FF); border-radius: 10px; color: white; }}
        </style>
    """, unsafe_allow_html=True)

# ============================================================================
# SESSION STATE 
# ============================================================================
if 'analyzer' not in st.session_state: st.session_state.analyzer = None
if 'variants_pool' not in st.session_state: st.session_state.variants_pool = []
if 'top_triplets' not in st.session_state: st.session_state.top_triplets = []
if 'generated_quads' not in st.session_state: st.session_state.generated_quads = []
if 'dark_mode' not in st.session_state: st.session_state.dark_mode = False
if 'warnings' not in st.session_state: st.session_state.warnings = []

apply_custom_css(st.session_state.dark_mode)

# ============================================================================
# HEADER
# ============================================================================
col1, col2, col3 = st.columns([1, 2, 1])
with col1:
    if st.button("SOARE/LUNA Toggle"):
        st.session_state.dark_mode = not st.session_state.dark_mode
        st.rerun()
with col2:
    st.markdown("""
        <div class="main-header">
            <h1>Lottery Quad Builder v7.1</h1>
            <p>Triplets to 4/4 (12/66) | Fara Overlap & Stabil</p>
        </div>
    """, unsafe_allow_html=True)
with col3:
    st.markdown("**v7.1.0**")

# ============================================================================
# SIDEBAR
# ============================================================================
with st.sidebar:
    st.header("Import Extrageri")
    uploaded_file = st.file_uploader("TXT Extrageri (5000+)", type=['txt'])
    if uploaded_file is not None:
        try:
            content = uploaded_file.read().decode('utf-8')
            if st.button("Analizeaza", type="primary"):
                st.session_state.warnings = [] 
                with st.spinner("Analizand..."):
                    # V7.1 FIX: Apel la functie dedicata
                    st.session_state.analyzer = handle_analysis_process(content)
                if st.session_state.analyzer and len(st.session_state.analyzer.draws) > 0:
                    st.success("Extrageri OK!")
                    st.balloons()
                else:
                    st.error("Fisierul nu contine extrageri valide (12/66).")
        except Exception as e:
            st.error(f"Eroare la incarcare: {e}")

    if st.session_state.analyzer and len(st.session_state.analyzer.draws) > 0:
        st.success("Extrageri incarcate!")

    st.markdown("---")
    st.header("Import Pool Variante (Optional)")
    pool_file = st.file_uploader("CSV/TXT Pool (10000+)", type=['csv', 'txt'])
    
    if pool_file is not None:
        st.info(f"Fisier Pool: **{pool_file.name}** gata de procesare.")
        
        if st.button("Incarca Pool"):
            st.session_state.variants_pool = [] 
            try:
                with st.spinner("Procesam pool-ul..."):
                    
                    if pool_file.name.endswith('.txt'):
                        content = pool_file.read().decode('utf-8')
                        df = pd.DataFrame({'Variant': content.splitlines()})
                    else: 
                        df = pd.read_csv(pool_file)
                        
                    variants = []
                    num_cols = [col for col in df.columns if 'Num' in col or 'n' in col.lower()]
                    variant_col = [col for col in df.columns if 'Variant' in col]

                    if variant_col:
                        for _, row in df.iterrows():
                            raw_string = str(row[variant_col[0]]).strip()
                            
                            if ',' in raw_string:
                                combination_string = raw_string.split(',', 1)[1].strip()
                            else:
                                combination_string = raw_string

                            raw_nums = combination_string.replace('-', ' ').split() 
                            
                            nums = []
                            for x in raw_nums:
                                if x.strip().isdigit():
                                    nums.append(int(x.strip()))
                            
                            if len(nums) >= 1: 
                                variants.append(sorted(nums))
                    
                    elif len(num_cols) >= 2: 
                        data_cols = num_cols[1:] 
                        for _, row in df.iterrows():
                            try:
                                nums = [int(row[col]) for col in data_cols if pd.notna(row[col])]
                                if len(nums) >= 1: 
                                    variants.append(sorted(nums))
                            except (ValueError, TypeError): continue
                    
                    elif len(num_cols) == 1:
                         data_cols = num_cols
                         for _, row in df.iterrows():
                            try:
                                nums = [int(row[col]) for col in data_cols if pd.notna(row[col])]
                                if len(nums) >= 1: 
                                    variants.append(sorted(nums))
                            except (ValueError, TypeError): continue
                    
                    else:
                        raise ValueError("Coloana 'Variant' sau cel putin o coloana numerica nu au fost gasite.")

                if len(variants) > 0:
                    st.session_state.variants_pool = variants
                    st.success(f"**{len(variants)}** variante incarcate!")
                else:
                    st.warning(f"Fisierul a fost procesat, dar **nu s-au gasit variante valide**.")
            
            except Exception as e:
                st.error(f"Eroare la incarcare Pool: {e}")

    st.markdown("---")
    st.subheader("Setari")
    
    top_n = st.slider("Top Triplete de Extras", 500, 5000, 2000)
    st.session_state.settings = {
        'top_n': top_n,
    }

    if st.session_state.warnings:
        with st.expander("Avertismente & Note", expanded=True):
            for warn in st.session_state.warnings:
                st.caption(warn)
    
    st.markdown("---")
    if st.session_state.analyzer:
        st.metric("Extrageri Incarcate", len(st.session_state.analyzer.draws))
    st.metric("Triplete Posibile", "45,760")

# ============================================================================
# MAIN TABS
# ============================================================================
if not st.session_state.analyzer or len(st.session_state.analyzer.draws) == 0: st.stop()

analyzer = st.session_state.analyzer
settings = st.session_state.settings

tab1, tab2, tab3 = st.tabs(["Analiza Extrageri", "Extrage din Pool", "Genereaza 4/4"])

with tab1:
    st.header("Analiza Extrageri")
    col1, col2, col3 = st.columns(3)
    with col1: st.metric("Triplete Ponderate", len(analyzer.triplets_weighted))
    with col2: st.metric("Suma Medie", f"{analyzer.sum_mu:.1f}")
    with col3: st.metric("Deviatie Suma", f"{analyzer.sum_sigma:.1f}")

    if st.button("Extrage Triplete din Extrageri"):
        with st.spinner("Extragem..."):
            extractor = TripletExtractor(analyzer)
            triplets = extractor.extract_top_triplets(None, settings['top_n'])
            st.session_state.top_triplets = triplets
        st.success(f"S-au extras {len(triplets)} triplete!")

    if st.session_state.top_triplets:
        df = pd.DataFrame([
            {'Triplet': f"{t[0][0]}-{t[0][1]}-{t[0][2]}", 'Scor': f"{t[1]:.4f}"}
            for t in st.session_state.top_triplets[:50]
        ])
        st.dataframe(df, use_container_width=True)
        txt_content = "\n".join([f"{t[0][0]}-{t[0][1]}-{t[0][2]} {t[1]:.4f}" for t in st.session_state.top_triplets])
        st.download_button("Descarca TXT", txt_content, "triplets_from_draws.txt")

with tab2:
    st.header("Extrage din Pool Variante")
    if not st.session_state.variants_pool:
        st.warning("Importati pool-ul mai intai (din bara laterala).")
    else:
        st.info(f"Pool: {len(st.session_state.variants_pool)} variante")

        if st.button("Gaseste Triplete Bune din Pool"):
            if len(st.session_state.variants_pool) == 0:
                st.error("Pool-ul este gol!")
            else:
                progress_bar = st.progress(0)
                status = st.empty()
                status.text("Pasul 1/2: Extragem...")
                progress_bar.progress(30)
                extractor = TripletExtractor(analyzer)
                triplets = extractor.extract_top_triplets(
                    st.session_state.variants_pool, settings['top_n']
                )
                progress_bar.progress(70)
                status.text("Pasul 2/2: Sortare si filtrare...")
                st.session_state.top_triplets = triplets
                progress_bar.progress(100)
                status.empty()
                progress_bar.empty()

                if len(triplets) == 0: st.warning("Nu s-au gasit triplete in Pool!")
                else: st.success(f"S-au gasit {len(triplets)} triplete!")

        if st.session_state.top_triplets and len(st.session_state.top_triplets) > 0:
            df = pd.DataFrame([
                {'Triplet': f"{t[0][0]}-{t[0][1]}-{t[0][2]}", 'Scor': f"{t[1]:.4f}"}
                for t in st.session_state.top_triplets[:500]
            ])
            st.dataframe(df, use_container_width=True)

with tab3:
    st.header("Genereaza 4/4")

    if not st.session_state.top_triplets or len(st.session_state.top_triplets) == 0:
        st.warning("Extrageti triplete mai intai (din Tab 1 sau Tab 2).")
    else:
        max_possible_quads = len(st.session_state.top_triplets) 
        
        num_quads_slider_max = min(2000, max_possible_quads * 2) 
        num_quads = st.slider("Cate Variante 4/4", 100, num_quads_slider_max, min(500, num_quads_slider_max))
        
        if max_possible_quads < num_quads: 
             st.warning(f"Pool de triplete mic ({max_possible_quads}). Creste 'Top Triplete' in Setari.")

        # V7.1 FIX (TypeError fix): Filtrare stricta pe elemente valide (lista de 3 numere)
        valid_triplets = [(t, s) for t, s in st.session_state.top_triplets if isinstance(t, list) and len(t) == 3]

        triplet_options = [f"{t[0]}-{t[1]}-{t[2]}" for t, _ in valid_triplets]
        triplet_map_score = {f"{t[0]}-{t[1]}-{t[2]}": f"{s:.4f}" for t, s in valid_triplets}
        triplet_map = {f"{t[0]}-{t[1]}-{t[2]}": (t, score) for t, score in valid_triplets}
        
        # Multiselect limitat la 500 (Problema 5)
        selected_triplet_strs = st.multiselect(
            "Selecteaza Triplete (Top 500 afisate, poti cauta restul)", 
            options=triplet_options, 
            default=triplet_options[:min(500, len(triplet_options))], 
            format_func=lambda x: f"{x} (Scor: {triplet_map_score.get(x, 'N/A')})"
        )

        if st.button("Genereaza 4/4 Unice", type="primary"):
            if not selected_triplet_strs:
                st.warning("Selectati cel putin un triplet.")
            else:
                with st.spinner("Generam... (Paralelizare activa)"):
                    selected_triplets = []
                    for t_str in selected_triplet_strs:
                         t_tuple, score = triplet_map.get(t_str)
                         if t_tuple is not None:
                            selected_triplets.append((t_tuple, score))
                         
                    extender = QuadExtender(analyzer)
                    quads = extender.generate_quads_from_triplets(
                        selected_triplets, num_quads
                    )
                    st.session_state.generated_quads = quads
                st.success(f"{len(quads)} quad-uri generate!")
                st.balloons()

        if st.session_state.generated_quads:
            quads_list = st.session_state.generated_quads
            st.markdown("---")
            st.subheader("Rezultate & Performanta")
            
            optimizer = CoverageOptimizer()
            cov = optimizer.calculate_coverage(quads_list)
            
            col1, col2, col3, col4 = st.columns(4)
            with col1: st.metric("Scor Mediu", f"{cov['avg_score']:.2f}")
            with col2: st.metric("Scor Max", f"{cov['max_score']:.2f}")
            with col3: st.metric("Sansa Estimata (Ajustata)", f"{cov['estimated_win_chance']:.2f}%")
            with col4: st.metric("Quad-uri Generate", len(quads_list))

            st.markdown("---")
            st.subheader("Backtest pe Extrageri Recente")
            
            if st.button("Test pe Ultimele 100 Extrageri"):
                if len(analyzer.draws) < 100:
                    st.warning(f"Doar {len(analyzer.draws)} extrageri disponibile. Nu se poate rula backtest-ul.")
                else:
                    with st.spinner("Rulare backtest..."):
                        backtester = Backtester(analyzer)
                        avg_2, avg_3, avg_4, expected_val = backtester.run_backtest(quads_list, num_draws=100)
                    
                    st.success("Backtest Finalizat!")
                    b_col1, b_col2, b_col3, b_col4 = st.columns(4)
                    with b_col1: st.metric("Avg Hits 2/4", f"{avg_2:.2f}")
                    with b_col2: st.metric("Avg Hits 3/4", f"{avg_3:.2f}")
                    with b_col3: st.metric("Avg Hits 4/4", f"{avg_4:.2f}")
                    with b_col4: st.metric("Valoare Asteptata", f"{expected_val:.2f}")


            st.markdown("---")
            st.subheader("Lista Quad-urilor")
            
            df_display = pd.DataFrame([
                {
                    'Index': i + 1,
                    'Quad': f"{q[0]}-{q[1]}-{q[2]}-{q[3]}",
                    'Scor': f"{s:.2f}",
                    'Triplet_Baza': f"{t[0]}-{t[1]}-{t[2]}"
                }
                for i, (q, s, t) in enumerate(quads_list)
            ])
            st.dataframe(df_display, use_container_width=True)

            txt_lines_clean = []
            for i, (q, s, t) in enumerate(quads_list):
                combination_str = " ".join(map(str, q))
                txt_lines_clean.append(f"{i+1}, {combination_str}")
                
            txt_content_clean = "\n".join(txt_lines_clean)
            st.download_button("Descarca TXT (ID, Combinatie)", txt_content_clean, "quads_4of4_clean.txt")

            df_export_clean = pd.DataFrame([
                {
                    'ID': i + 1,
                    'Combinatie': " ".join(map(str, q)) 
                }
                for i, (q, s, t) in enumerate(quads_list)
            ])

            csv_content_clean = df_export_clean.to_csv(index=False)
            st.download_button("Descarca CSV (ID, Combinatie)", csv_content_clean, "quads_4of4_clean.csv")

# ============================================================================
# FOOTER
# ============================================================================
st.markdown("---")
st.caption("v7.1.0 | Fara constrangeri de overlap | Joaca responsabil")
