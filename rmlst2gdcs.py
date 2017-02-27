#!/usr/bin/env python
from accessoryfunctions.accessoryFunctions import *
import shutil
__author__ = 'adamkoziol'


class GDCS(object):

    def runner(self):
        """
        Run the methods in the correct order
        """
        # Extract the alleles from the database
        self.alleleparser()
        # Create .fasta files of the the allele sequences
        self.alleleretriever()
        # Align the alleles
        self.allelealigner()
        # Find probes
        self.probefinder()
        #
        self.probes()

    def alleleparser(self):
        """
        Parse a .csv file of rMLST alleles, and find all alleles for each gene for each organism of interest present in
        the file
        """
        import csv
        printtime('Parsing alleles', self.start)
        # Initialise each organism of interest as a sub-dictionary
        for organism in self.organisms:
            self.alleledict[organism] = dict()
            # Add an Enterobacteriaceae-specific entry
            if organism == 'Escherichia' or organism == 'Salmonella' or organism == 'Enterobacter':
                self.alleledict['Enterobacteriaceae'] = dict()
        # Get all the gene names into a list
        with open(self.rmlstfile, 'rb') as rmlst:
            # Grab the header from the file
            header = rmlst.readline().rstrip()
            # Find all the gene names in the header
            self.genes = [gene for gene in header.split(',') if gene.startswith('BACT')]
        # Further prepare the dictionary to store a set of alleles for each gene
        for organism in self.organisms:
            for gene in self.genes:
                self.alleledict[organism][gene] = set()
                if organism == 'Escherichia' or organism == 'Salmonella' or organism == 'Enterobacter':
                    self.alleledict['Enterobacteriaceae'][gene] = set()
        # Read the csv file into memory as a dictionary
        rmlstdict = csv.DictReader(open(self.rmlstfile))
        # Iterate through all the entries in the dictionary
        for row in rmlstdict:
            # Discard entries that do not match organisms of interest
            if row['Genus'] in self.organisms:
                # Find the allele for each gene
                for gene in self.genes:
                    # Alleles that are not present ('N') don't have a sequence, so they are ignored
                    if row[gene] != 'N':
                        # Remove the 'actual' allele from the sample profile e.g. for 10 692 (N), the (N) is removed.
                        # Additionally, the 10 692 are split into 10 and 692
                        try:
                            allele = row[gene].split(' (')[0]
                        except IndexError:
                            allele = row[gene]
                        # Split on the space between two alleles (10 692) and add both to the set
                        for alleles in allele.split(' '):
                            # Add the integer of the allele to the set
                            self.alleledict[row['Genus']][gene].add(int(alleles))
                            # Add all the Enterobacteriaceae to a combined entry
                            if row['Genus'] == 'Escherichia' or row['Genus'] == 'Salmonella' \
                                    or row['Genus'] == 'Enterobacter':
                                self.alleledict['Enterobacteriaceae'][gene].add(int(alleles))

    def alleleretriever(self):
        """
        Retrieve the required alleles from a file of all alleles, and create organism-specific allele files
        """
        from Bio import SeqIO
        printtime('Retrieving alleles', self.start)
        # Index all the records in the allele file
        printtime('Loading rMLST records', self.start)
        recorddict = SeqIO.index(self.allelefile, 'fasta')
        printtime('Creating allele output files', self.start)
        # Create the organism-specific files of alleles
        for organism in sorted(self.alleledict):
            # Make an object to store information for each strain
            metadata = MetadataObject()
            metadata.organism = organism
            metadata.path = self.path
            metadata.outpath = os.path.join(self.path, 'outputalleles', organism, '')
            # Delete and recreate the output path - as the files are appended to each time, they will be too large if
            # this script is run more than once
            try:
                shutil.rmtree(metadata.outpath)
            except OSError:
                pass
            make_path(metadata.outpath)
            metadata.combined = '{}gdcs_alleles.fasta'.format(metadata.outpath)
            metadata.allelefiles = list()
            with open(metadata.combined, 'wb') as combined:
                for gene, alleles in sorted(self.alleledict[organism].items()):
                    # Open the file to append
                    allelefiles = '{}{}.tfa'.format(metadata.outpath, gene)
                    metadata.allelefiles.append(allelefiles)
                    with open(allelefiles, 'ab') as allelefile:
                        # Write each allele record to the file
                        for allele in sorted(alleles):
                            SeqIO.write(recorddict['{}_{}'.format(gene, allele)], allelefile, 'fasta')
                            SeqIO.write(recorddict['{}_{}'.format(gene, allele)], combined, 'fasta')
            # Add the populated metadata to the list
            self.samples.append(metadata)

    def allelealigner(self):
        """

        """
        from Bio.Align.Applications import ClustalOmegaCommandline
        from threading import Thread
        printtime('Aligning alleles', self.start)
        # Create the threads for the analysis
        for sample in self.samples:
            threads = Thread(target=self.alignthreads, args=())
            threads.setDaemon(True)
            threads.start()
        for sample in self.samples:
            sample.alignpath = os.path.join(self.path, 'alignedalleles', sample.organism, '')
            make_path(sample.alignpath)
            sample.alignedalleles = list()
            for outputfile in sample.allelefiles:
                aligned = os.path.join(sample.alignpath, os.path.basename(outputfile))
                sample.alignedalleles.append(aligned)
                # Create the command line call
                clustalomega = ClustalOmegaCommandline(infile=outputfile,
                                                       outfile=aligned,
                                                       threads=4,
                                                       auto=True)
                sample.clustalomega = str(clustalomega)
                self.queue.put((sample, clustalomega, outputfile, aligned))
        self.queue.join()

    def alignthreads(self):
        while True:
            sample, clustalomega, outputfile, aligned = self.queue.get()
            if not os.path.isfile(aligned):
                # Perform the alignments
                try:
                    clustalomega()
                # Files with a single sequence cannot be aligned. Copy the original file over to the aligned folder
                except Exception:
                    shutil.copyfile(outputfile, aligned)
            dotter()
            self.queue.task_done()

    def probefinder(self):
        from Bio import AlignIO
        from Bio.Align import AlignInfo
        import numpy
        printtime('Finding and filtering probe sequences', self.start)
        for sample in self.samples:
            # A list to store the metadata object for each alignment
            sample.probe = list()
            if sample.organism == 'Salmonella':
                for align in sample.alignedalleles:
                    # Create an object to store all the information for each alignment file
                    metadata = GenObject()
                    metadata.name = os.path.basename(align).split('.')[0]
                    metadata.alignmentfile = align
                    # Create an alignment object from the alignment file
                    metadata.alignment = AlignIO.read(align, 'fasta')
                    metadata.summaryalign = AlignInfo.SummaryInfo(metadata.alignment)
                    # The dumb consensus is a very simple consensus sequence calculated from the alignment. Default
                    # parameters of threshold=.7, and ambiguous='X' are used
                    consensus = metadata.summaryalign.dumb_consensus()
                    metadata.consensus = str(consensus)
                    # The position-specific scoring matrix (PSSM) stores the frequency of each based observed at each
                    # location along the entire consensus sequence
                    metadata.pssm = metadata.summaryalign.pos_specific_score_matrix(consensus)
                    metadata.identity = list()
                    # Find the prevalence of each base for every location along the sequence
                    for line in metadata.pssm:
                        bases = [line['A'], line['C'], line['G'], line['T']]
                        # Calculate the frequency of the most common base
                        metadata.identity.append(float('{:.2f}'.format(max(bases) / sum(bases) * 100)))
                    metadata.windows = list()
                    passing = False
                    # Create sliding windows of size 20 - 100 from the list of identities for each column of the alignment
                    for i in reversed(range(self.min, self.max + 1)):
                        if not passing:
                            windowdata = MetadataObject()
                            windowdata.size = i
                            windowdata.max = 0
                            # windowdata.hits = dict()
                            windowdata.sliding = list()
                            # Create a counter to store the starting location of the window in the sequence
                            n = 0
                            # Create sliding windows from the range of window sizes for the length of the list of identities
                            windows = self.window(metadata.identity, i)
                            #
                            # cutoff = 80
                            # metadata.probes = dict()
                            # windowdata.location = '{}:{}'.format(n, n + i)
                        #     metadata.probes[probelength] = dict()
                        #     if not windowdata.hits:
                            for window in windows:
                                slidingdata = MetadataObject()
                                if min(window) > self.cutoff:
                                    slidingdata.location = '{}:{}'.format(n, n + i)
                                    slidingdata.min = min(window)
                                    slidingdata.mean = float('{:.2f}'.format(numpy.mean(window)))
                                    slidingdata.sequence = str(consensus[n:n+i])
                                    windowdata.max = slidingdata.mean if slidingdata.mean >= windowdata.max else windowdata.max
                                    windowdata.min = slidingdata.mean if slidingdata.mean <= windowdata.max else windowdata.min
                                    # windowdata.hits.update({slidingdata.location: {slidingdata.min: slidingdata.mean}})
                                    windowdata.sliding.append(slidingdata)
                                    passing = True
                                n += 1

                                # pass
                                # metadata.probes[probelength].update({i: {min(window): float('{:.2f}'.format(numpy.mean(window)))}})
                    #
                    # for length in metadata.probes:
                    #     for probe in metadata.probes[length]:
                    #         for minimum, mean in metadata.probes[length][probe].items():
                    #             print sample.organism, metadata.name, length, probe, minimum, mean
                    #             print sample.organism, metadata.name, i, '{} - {}'.format(n, n + i), min(window), \
                    #                 float('{:.2f}'.format(numpy.mean(window))), window
                    #             print consensus[n:n+i]

                            metadata.windows.append(windowdata)
                    dotter()
                    sample.probe.append(metadata)
                    # print i, min(win), float('{:.2f}'.format(numpy.mean(win))), win
        #     print line, max(bases), sum(bases)

    def probes(self):
        # quit()
        for sample in self.samples:
            print sample.organism
            # print sample.datastore
            for probe in sample.probe:
                for window in probe.windows:
                    passed = False
                    for sliding in window.sliding:

                        if sliding.datastore and sliding.mean == window.max and sliding.mean >= window.min and not passed:
                            print sample.organism, probe.name, window.size, window.max, sliding.datastore
                            passed = True
                # print probe.datastore

    @staticmethod
    def window(iterable, size):
        """
        https://coderwall.com/p/zvuvmg/sliding-window-in-python
        :param iterable:
        :param size:
        :return:
        """
        i = iter(iterable)
        win = []
        for e in range(0, size):
            win.append(next(i))
        yield win
        for e in i:
            win = win[1:] + [e]
            yield win

    def __init__(self, args, startingtime):
        """
        :param args: command line arguments
        :param startingtime: time the script was started
        """
        import multiprocessing
        from Queue import Queue
        # Initialise variables
        self.start = startingtime
        # Define variables based on supplied arguments
        if args.path.endswith('/'):
            self.path = args.path
        else:
            self.path = os.path.join(args.path, '')
        assert os.path.isdir(self.path), u'Supplied path is not a valid directory {0!r:s}'.format(self.path)
        self.rmlstfile = args.file
        self.organisms = args.organisms.split(',')
        self.allelefile = args.allelefile
        self.min = args.min
        self.max = args.max
        self.cutoff = args.cutoff
        self.genes = list()
        self.alleledict = dict()
        self.samples = list()
        self.cpus = multiprocessing.cpu_count()
        self.queue = Queue(maxsize=self.cpus)
        # Run the analyses
        self.runner()

if __name__ == '__main__':
    # Argument parser for user-inputted values, and a nifty help menu
    from argparse import ArgumentParser
    import time
    # Parser for arguments
    parser = ArgumentParser(description='For all organisms of interest, create .fasta files containing each allele'
                                        'found for every rMLST gene')
    parser.add_argument('path',
                        help='Specify input directory')
    parser.add_argument('-f', '--file',
                        required=True,
                        help='Name of .csv file containing rMLST information. Must be within the supplied path')
    parser.add_argument('-o', '--organisms',
                        default='Escherichia,Listeria,Salmonella,Enterobacter',
                        help='Comma-separated list of organisms of interest')
    parser.add_argument('-a', '--allelefile',
                        required=True,
                        help='File of combined rMLST alleles. This file must be within the supplied path')
    parser.add_argument('-m', '--min',
                        default=20,
                        help='Minimum size of probe to create')
    parser.add_argument('-M', '--max',
                        default=100,
                        help='Maximum size of probe to create')
    parser.add_argument('-c', '--cutoff',
                        default=80,
                        help='Cutoff percent identity of a nucleotide location to use')
    # Get the arguments into an object
    arguments = parser.parse_args()
    arguments.pipeline = False
    # Define the start time
    start = time.time()

    # Run the script
    GDCS(arguments, start)

    # Print a bold, green exit statement
    print '\033[92m' + '\033[1m' + "\nElapsed Time: %0.2f seconds" % (time.time() - start) + '\033[0m'
