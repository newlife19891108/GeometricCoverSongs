"""
Programmer: Chris Tralie, 12/2016 (ctralie@alumni.princeton.edu)
Purpose: To implement similarity network fusion approach described in
[1] Wang, Bo, et al. "Unsupervised metric fusion by cross diffusion." Computer Vision and Pattern Recognition (CVPR), 2012 IEEE Conference on. IEEE, 2012.
[2] Wang, Bo, et al. "Similarity network fusion for aggregating data types on a genomic scale." Nature methods 11.3 (2014): 333-337.
"""
import numpy as np
import matplotlib.pyplot as plt
from scipy import sparse
import scipy.io as sio
import time
import os
from EvalStatistics import *

def getW(D, K, Mu = 0.5):
    """
    Return affinity matrix
    :param D: Self-similarity matrix
    :param K: Number of nearest neighbors
    """
    #W(i, j) = exp(-Dij^2/(mu*epsij))
    DSym = 0.5*(D + D.T)
    np.fill_diagonal(DSym, 0)

    Neighbs = np.partition(DSym, K+1, 1)[:, 0:K+1]
    MeanDist = np.mean(Neighbs, 1)*float(K+1)/float(K) #Need this scaling
    #to exclude diagonal element in mean
    #Equation 1 in SNF paper [2] for estimating local neighborhood radii
    #by looking at k nearest neighbors, not including point itself
    Eps = MeanDist[:, None] + MeanDist[None, :] + DSym
    Eps = Eps/3
    W = np.exp(-DSym**2/(2*(Mu*Eps)**2))
    return W

#Cross-Affinity Matrix.  Do a special weighting of nearest neighbors
#so that there are a proportional number of similarity neighbors
#and cross neighbors
def getWCSMSSM(SSMA, SSMB, CSMAB, K, Mu = 0.5):
    N = SSMA.shape[0]
    M = SSMB.shape[0]
    #Split the neighbors evenly between the CSM
    #and SSM parts of each row
    k1 = int(K*float(N)/(M+N))
    k2 = K - k1

    WSSMA = getW(SSMA, k1, Mu)
    WSSMB = getW(SSMB, k2, Mu)

    Neighbs1 = np.partition(CSMAB, k2, 1)[:, 0:k2]
    MeanDist1 = np.mean(Neighbs1, 1)

    Neighbs2 = np.partition(CSMAB, k1, 0)[0:k1, :]
    MeanDist2 = np.mean(Neighbs2, 0)
    Eps = MeanDist1[:, None] + MeanDist2[None, :] + CSMAB
    Eps /= 3
    WCSMAB = np.exp(-CSMAB**2/(2*(Mu*Eps)**2))


    #Setup matrix  [ SSMA  CSMAB ]
    #              [ CSMBA SSMB ]
    W = np.zeros((N+M, N+M))
    W[0:N, 0:N] = WSSMA
    W[0:N, N::] = WCSMAB
    W[N::, 0:N] = WCSMAB.T
    W[N::, N::] = WSSMB
    return W

#Probability matrix
def getP(W, diagRegularize = False):
    if diagRegularize:
        P = 0.5*np.eye(W.shape[0])
        WNoDiag = np.array(W)
        np.fill_diagonal(WNoDiag, 0)
        RowSum = np.sum(WNoDiag, 1)
        RowSum[RowSum == 0] = 1
        P = P + 0.5*WNoDiag/RowSum[:, None]
        return P
    else:
        RowSum = np.sum(W, 1)
        RowSum[RowSum == 0] = 1
        P = W/RowSum[:, None]
        return P

#Same thing as P but restricted to K nearest neighbors only
#(**note that nearest neighbors here include the element itself)
def getS(W, K):
    N = W.shape[0]
    J = np.argpartition(-W, K, 1)[:, 0:K]
    I = np.tile(np.arange(N)[:, None], (1, K))
    V = W[I.flatten(), J.flatten()]
    #Now figure out L1 norm of each row
    V = np.reshape(V, J.shape)
    SNorm = np.sum(V, 1)
    SNorm[SNorm == 0] = 1
    V = V/SNorm[:, None]
    [I, J, V] = [I.flatten(), J.flatten(), V.flatten()]
    S = sparse.coo_matrix((V, (I, J)), shape=(N, N)).tocsr()
    return S


#Ws: An array of NxN affinity matrices for N songs
#K: Number of nearest neighbors
#NIters: Number of iterations
#reg: Identity matrix regularization parameter for self-similarity promotion
#PlotNames: Strings describing different similarity measurements.
#If this array is specified, an animation will be saved of the cross-diffusion process
def doSimilarityFusionWs(Ws, K = 5, NIters = 20, reg = 1, PlotNames = [], verboseTimes = False):
    tic = time.time()
    #Full probability matrices
    Ps = [getP(W) for W in Ws]
    #Nearest neighbor truncated matrices
    Ss = [getS(W, K) for W in Ws]

    #Now do cross-diffusion iterations
    Pts = [np.array(P) for P in Ps]
    nextPts = [np.zeros(P.shape) for P in Pts]
    if verboseTimes:
        print "Time getting Ss and Ps: ", time.time() - tic

    N = len(Pts)
    AllTimes = []
    for it in range(NIters):
        if len(PlotNames) == N:
            k = int(np.ceil(np.sqrt(N)))
            for i in range(N):
                res = np.argmax(Pts[i][0:80, 80::], 1)
                res = np.sum(res == np.arange(80))
                plt.subplot(k, k, i+1)
                Im = 1.0*Pts[i]
                Idx = np.arange(Im.shape[0], dtype=np.int64)
                Im[Idx, Idx] = 0
                plt.imshow(Im, interpolation = 'none')
                plt.title("%s: %i/80"%(PlotNames[i], res))
                plt.axis('off')
            plt.savefig("SSMFusion%i.png"%it, dpi=150, bbox_inches='tight')
        for i in range(N):
            nextPts[i] *= 0
            tic = time.time()
            for k in range(N):
                if i == k:
                    continue
                nextPts[i] += Pts[k]
            nextPts[i] /= float(N-1)

            #tic = time.time()
            #nextPts[i] = SsD[i].dot(nextPts[i].dot(SsD[i].T))
            #toc = time.time()
            #print toc - tic, " ",

            #Need S*P*S^T, but have to multiply sparse matrix on the left
            tic = time.time()
            A = Ss[i].dot(nextPts[i].T)
            nextPts[i] = Ss[i].dot(A.T)
            toc = time.time()
            AllTimes.append(toc - tic)

            if reg > 0:
                nextPts[i] += reg*np.eye(nextPts[i].shape[0])

        Pts = nextPts
    if verboseTimes:
        print "Total Time multiplying: ", np.sum(np.array(AllTimes))
    FusedScores = np.zeros(Pts[0].shape)
    for Pt in Pts:
        FusedScores += Pt
    return FusedScores/N

#Same as above, except scores is an array of NxN distance matrices
def doSimilarityFusion(Scores, K = 5, NIters = 20, reg = 1, PlotNames = []):
    #Affinity matrices
    Ws = [getW(D, K) for D in Scores]
    return doSimilarityFusionWs(Ws, K, NIters, reg, PlotNames)

if __name__ == '__main__':
    X = sio.loadmat('Scores4.mat')
    PlotNames = ['ScoresSSMs', 'ScoresHPCP', 'ScoresMFCCs', 'ScoresSNF']
    #PlotNames = ['ScoresJumps10', 'ScoresJumps60', 'ScoresCurvs60']
    Scores = [X[s] for s in PlotNames]
    for i in range(len(Scores)):
        #Smith waterman returns larger scores for more similar songs,
        #but we want the graph kernel to be closer to 0 for similar objects
        Scores[i] = 1.0/Scores[i]

    W = 20 #Number of nearest neighbors to take in the network
    FusedScores = doSimilarityFusion(Scores, W, 20, 1, PlotNames)
    fout = open("resultsFusion.html", "a")
    getCovers80EvalStatistics(FusedScores, 160, 80,  [1, 25, 50, 100], fout, name = "Jumps10/Jumps60/Curvs60, 20NN, 1Reg")
    fout.close()

if __name__ == '__main__2':
    #X = sio.loadmat('SHSDataset/SHSScores.mat')
    X = sio.loadmat('Covers1000Results.mat')
    #SHSIDs = sio.loadmat("SHSDataset/SHSIDs.mat")
    #Ks = SHSIDs['Ks'].flatten()
    Ks = getCovers1000Ks()
    PlotNames = ['Chromas', 'SSMs', 'MFCCs', 'SNF']
    Scores = [X[s] for s in PlotNames]
    print Scores
    N = Scores[0].shape[0]
    fout = open("Covers1000Results.html", "a")
    fout.write("""
    <table border = "1" cellpadding = "10">
<tr><td><h3>Name</h3></td><td><h3>Mean Rank</h3></td><td><h3>Mean Reciprocal Rank</h3></td><td><h3>Median Rank</h3></td><td><h3>Top-01</h3></td><td><h3>Top-25</h3></td><td><h3>Top-50</h3></td><td><h3>Top-100</h3></td></tr>      """)
    for i in range(len(Scores)):
        #Smith waterman returns larger scores for more similar songs,
        #but we want the graph kernel to be closer to 0 for similar objects
        getEvalStatistics(Scores[i], Ks, [1, 25, 50, 100], fout, PlotNames[i])
        Scores[i] = 1.0/(0.1 + Scores[i])
    if 'SNF' in X:
        getEvalStatistics(X['SNF'], Ks, [1, 25, 50, 100], fout, 'Early SNF')
    W = 20 #Number of nearest neighbors to take in the network
    FusedScores = doSimilarityFusion(Scores, W, 20, 1, PlotNames)
    AllRes = {}
    for F in PlotNames + ['SNF']:
        if F in X:
            AllRes[F] = X[F]
    AllRes['LateSNF'] = FusedScores
    sio.savemat('SHSDataset/SHSScores.mat', AllRes)
    getEvalStatistics(FusedScores, Ks, [1, 25, 50, 100], fout, "Late SNF")
    fout.write("</table>")
    fout.close()
