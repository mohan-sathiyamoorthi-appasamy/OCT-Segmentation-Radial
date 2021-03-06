import cv2
import matplotlib.pyplot as plt
import math
import numpy as np
import scipy.io
from scipy import sparse
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.sparse import csr_matrix, vstack
from scipy import interpolate
from scipy.signal import savgol_filter
import pandas as pd
import itertools
from scipy import signal
import statistics
import glob
import csv
import sys

axialRes = 6.7
lateralRes = 13.4
MATRIX_INDICES = [0,1,2,4,4,4,3,3,4,5]
matrixIndices = np.array(MATRIX_INDICES)
MIN_WEIGHTS = 0.00001
X_FILTER_SIZE = 40.2
Y_FILTER_SIZE = 20.1
SIGMA = 6
EDGE_FILTER = np.array([[0.2,0.6,0.2],[-0.2,-0.6,-0.2]])
NUM_LAYERS = 8
MAX_NUM_LAYERS = 8
numLayers = NUM_LAYERS
LAYER_INDICES  = [0,7,7,6,5,3,2,4,3,1]
layerIndices = np.array(LAYER_INDICES)
maxIndex = 0
uniqueLayerIndices = []

LATERAL_RESOLUTION = 2
AXIAL_RESOLUTION = 2.5
X_RESOLUTION = 13.4
Y_RESOLUTION = 6.7
X_STREL_SIZE = 40.2
Y_STREL_SIZE = 20.1

def normal_getBWImage(resizedImage):
    #normalization
    norm_img = np.zeros((resizedImageHeight,resizedImageWidth))     
    normalizedImage = cv2.normalize(resizedImage,norm_img, 0, 255, cv2.NORM_MINMAX)
    
         
    #Filtering image 
    size = 11
    std = 7
    kernel = fspecial_gauss(size,std)
    blurImage= cv2.filter2D(normalizedImage,-1, kernel,borderType=cv2.BORDER_CONSTANT) 
    
    #difference image
    diffImage = np.diff(blurImage,axis=0)          
   
    #padding    
    diffImage1 = cv2.copyMakeBorder(diffImage,1,0,0,0,cv2.BORDER_CONSTANT,0)
    
    #threshold image
    ret,thresh = cv2.threshold(diffImage1,190,255,cv2.THRESH_TOZERO_INV)   
    
    #get structuring element
    XStrelSize = round(X_STREL_SIZE/X_RESOLUTION)        
    YStrelSize = round(Y_STREL_SIZE/Y_RESOLUTION)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT,(XStrelSize,YStrelSize))
    
    #morphological operation
    opening = cv2.morphologyEx(thresh,cv2.MORPH_OPEN,kernel)    
    
    
    #get connected components
    num_labels,lables,stats,centroids = cv2.connectedComponentsWithStats(opening, connectivity=8)
    minClustersize = 130;
    sizes = stats[1:, -1]; num_labels = num_labels - 1
    filterImage = np.zeros((lables.shape))
    
    #remove unwanted clusters
    for i in range(0, num_labels):
        if sizes[i] >= minClustersize:
                filterImage[lables == i+1] = 255
                
    #closing image
    closing = cv2.morphologyEx( filterImage,cv2.MORPH_CLOSE,kernel) 
    closing =  np.delete(closing,[0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15],0)
    closing  = cv2.copyMakeBorder(closing,16,0,0,0,cv2.BORDER_CONSTANT,0)
    return closing

def fspecial_gauss(size, sigma):
    x, y = np.mgrid[-size//2 + 1:size//2 + 1, -size//2 + 1:size//2 + 1]
    g = np.exp(-((x**2 + y**2)/(2.0*sigma**2)))
    return g/g.sum()

def normalgetBorders(bwImage):
    
    #Add column both side Image 
    borderAddBWImage = addColumns(bwImage,1)
   
    newImageheight = borderAddBWImage.shape[0]
    newImagewidth = borderAddBWImage.shape[1]
    
    newImageSize = (newImageheight,newImagewidth)
    Edges,weightingMatrix = bwWeightingMatrix(borderAddBWImage,newImagewidth,newImageheight)
     
    #Cut Each border
    numBorder = 4
    lines = np.zeros([numBorder,newImagewidth])
    invalidIndices1 = []
    invalidIndex = []
    
    for iBorder in range(0,numBorder):
        if iBorder >0:
            x = np.arange(1,resizedImageWidth+1)
            y = lines[iBorder-1,x]
            removedInd = np.array(np.where((y == 0) | (y == resizedImageHeight-1)))
           
            x = np.delete(x,removedInd) 
            y = np.delete(y,removedInd)
            y = y.astype('int')
            
            arr = (y,x)
            invalidIndices = np.ravel_multi_index(arr,(newImageheight,newImagewidth),order ='F')
            invalidIndices1.append(invalidIndices)
            
        if iBorder < numBorder-1:
            yBottom = newImageheight-1 * np.ones(newImagewidth)
        else:
            yBottom = np.amax(lines,axis =0)
        
    #Get the Region to Cut 
        invalidIndex = np.array((invalidIndices1),dtype=object)
        invalidIndex = invalidIndex.flatten()
        if len(invalidIndex) > 0 and len(invalidIndex) <= 3:
            invalidIndex = np.hstack(invalidIndex.flatten())
      
        regionIndices = getRegion(newImageSize,[0] * newImagewidth,yBottom,0,0,invalidIndex,[])
        
    # Cut the Region to get the border 
        lines[iBorder,:] = cutRegion(newImageSize,regionIndices,Edges,weightingMatrix[((iBorder+1) % 2)])
        
    #Remove the added Column
    bwImageColremoved = borderAddBWImage[:,1:-1]
    
    bwImageColremoved1 = np.where((bwImageColremoved == 255),1, bwImageColremoved)
    imageHeight, imageWidth = bwImageColremoved1.shape
    lines = lines[:,1:-1]
    
    oddIndices = np.array((range(0,4,2)))
    evenIndices = np.array((range(1,4,2)))
    
    oddSortOrder = np.sort((np.nanmean((lines[oddIndices,:]),1),(range(0,len(oddIndices)))))
    evenSortOrder = np.sort((np.nanmean((lines[evenIndices,:]),1),(range(0,len(evenIndices)))))
    
    vector = np.vectorize(np.int)
    bottomBorders = lines[oddIndices[vector(oddSortOrder[1,:])]]
    topBorders = lines[evenIndices[vector(evenSortOrder[1,:])]]
    
    borders = np.flip(lines, axis=0)
    bordersFinal = np.zeros([4,imageWidth])
     
    #Replace extrapolated points (those that do not lie along ahyper-reflective band) with NaN
    for iBorder in range(0,4): 
        
        border = borders[iBorder,:]
        if np.mod(iBorder,2):
            border = border - 1
            border[border < 1] = 1
            
        imageWidthArr =np.array(range(0,imageWidth))
        imageWidthArr = imageWidthArr.astype('int')
        border = border.astype('int')
        
        arr = (border,imageWidthArr)
        ind = np.ravel_multi_index(arr,(imageHeight,imageWidth),order = 'F')
        ind = vector(ind)
       
        bwImageVec = bwImageColremoved1.flatten()   
        bwImagetype = bwImageVec.astype('int')
        val = bwImagetype[ind]
        
        indexValues = np.array(np.where(val == 0))
        indexValues = indexValues.flatten()

        first = indexValues[0]
        last = indexValues[-1]
        
        yStart,xStart = np.unravel_index(ind[first],(imageHeight,imageWidth),order = 'F') 
        yEnd,xEnd = np.unravel_index(ind[last],(imageHeight,imageWidth),order = 'F')
        
        xStart = xStart.astype('int')
        yStart = yStart.astype('int')
        bordersFinal[iBorder,xStart:xEnd+1] = border[xStart:xEnd+1]
         
    return bordersFinal

def addColumns(bwImage,numColumns):
    height,width = bwImage.shape
    leftColumns = bwImage[:,0]
    rightColumns = bwImage[:,-1]
    mx = np.zeros([height,width+2])
    mx[0:height,1:width+1] = bwImage
    mx[0:height,0] = leftColumns
    mx[0:height,-1] = rightColumns
    return mx

def bwWeightingMatrix(borderAddBWImage,width,height):    
    #----------------------------------------------------------------------
    #  Calculate the weights based on the image gradient.  Lower weights 
    #  are assigned to areas with a higher gradient
    #---------------------------------------------------------------------    
    #  Create two edge maps (one for edges that transition from dark->light
    #  in the vertical direction, and one for edges transitioning from 
    #  light->dark)
    
    borderAddBWImage = np.where((borderAddBWImage > 0),1,0)
    diffimage = np.diff(borderAddBWImage,axis=0)
      
    diffImage = cv2.copyMakeBorder(diffimage,1,0,0,0,cv2.BORDER_CONSTANT,0)
    
   
    lightDarkEdgeImage = np.where((diffImage > 0),1,0)
    darklightEdgeImage = np.where((diffImage < 0),1,0)
       
    ind  = np.where(((lightDarkEdgeImage == 0) & (borderAddBWImage == 1)))
    lightDarkEdgeImage[ind] =-1
       
    ind  = np.where(((darklightEdgeImage == 0) & (borderAddBWImage == 1)))
    darklightEdgeImage[ind] =-1
 
    #Calculate the gradient weights for each of the edge maps
    edges = createLattice(borderAddBWImage.shape)
    
    imageHeight,imageWidth = borderAddBWImage.shape
    maxIndex = imageHeight*imageWidth

    leftColIndices = np.arange(0,imageHeight-1)
    rightColIndices = np.arange(((imageHeight-1)*(imageWidth-2)) , maxIndex)
    
    columnIndices = np.concatenate((leftColIndices,rightColIndices),axis=0)
    imageIndices = np.setdiff1d((np.arange(0,edges.shape[0])), columnIndices)
    columnEdges = edges[columnIndices,:]
    imageEdges = edges[imageIndices,:]
    imageEdgesrow1 = imageEdges[:,0]
    imageEdgesrow2 = imageEdges[:,1]
    
    lightDarkEdgeImageVec = lightDarkEdgeImage.flatten(order='F')
    lightDarkGrandientWeights  = 2 - lightDarkEdgeImageVec[imageEdgesrow1] - lightDarkEdgeImageVec[imageEdgesrow2]
   
   
    darklightEdgeImageVec = darklightEdgeImage.flatten(order='F')
    darkLightGrandientWeights  = 2 - darklightEdgeImageVec[imageEdgesrow1] - darklightEdgeImageVec[imageEdgesrow2]
    
    #Combining weights of lightDark and DarkLight images
    weights_2 = ([(lightDarkGrandientWeights)],[(darkLightGrandientWeights)])

   
    #set the min_weights
    min_weights = 0.00001
    columnWeight = min_weights 
    
    min_value = 0
    max_value = 1
    
    columnEdges = columnEdges.astype('int')
    
    imageSize = borderAddBWImage.shape 
  
    totWeightsLightDark,totalEdges = generateWeightingMatrix(imageSize,imageEdges,weights_2[0],columnEdges,columnWeight)   
    totWeightsdarkLight,totalEdges = generateWeightingMatrix(imageSize,imageEdges,weights_2[1],columnEdges,columnWeight)
    
    return_weight=(totWeightsLightDark,totWeightsdarkLight)
    
    return totalEdges,return_weight

def createLattice(imagesize):
    imageHeight = imagesize[0]
    imageWidth = imagesize[1]
    
    image = np.arange(0,imageHeight*imageWidth)
    indexMatrix = np.reshape(image,(imageHeight,imageWidth),order='F')
    height,width = indexMatrix.shape
    
    startNodes = indexMatrix[0:height-1,:]
    startNodes =startNodes.flatten(order='F')
    endNodes = indexMatrix[1:height,:]
    endNodes =endNodes.flatten(order='F')
    edges = np.stack([startNodes,endNodes],axis=1)
    
    startNodes = indexMatrix[:,0:width-1]
    startNodes =startNodes.flatten(order='F')
    endNodes = indexMatrix[:,1:width]
    endNodes =endNodes.flatten(order='F')
    edge1 = np.stack([startNodes[:], endNodes[:]],axis=1)
    edges =np.vstack([edges, edge1])
    
    startNodes = indexMatrix[0:height-1,0:width-1]
    startNodes =startNodes.flatten(order='F')
    endNodes = indexMatrix[1:height,1:width]
    endNodes =endNodes.flatten(order='F')
    edge2 = np.stack([startNodes[:], endNodes[:]],axis=1)
    edges =np.vstack ([edges, edge2 ])


    startNodes = indexMatrix[1:height,0:width-1]
    startNodes =startNodes.flatten(order='F')
    endNodes = indexMatrix[0:height-1,1:width]
    endNodes =endNodes.flatten(order='F')
    edge3 = np.stack([startNodes[:], endNodes[:]],axis=1)
    edges =np.vstack ([edges, edge3])
    
    return edges

def generateWeightingMatrix(imageSize,imageEdges,GrandientWeights,columnEdges,columnWeight):  
    columnEdgesShape = columnEdges.shape[0]
    column = np.ones(columnEdgesShape)
    
    #set the column weights
    columnWeights = columnWeight * column
    
    min_value = 0
    max_value = 1
    
    imageWeights = columnWeight
    weightLength = len(GrandientWeights)
    
    if weightLength > 0:
        for index in range(0,weightLength):
             
            normalizeValue = normalizeValues(GrandientWeights[index],min_value,max_value)     
            imageWeights = imageWeights + normalizeValue
    else:
        normalizeValue = normalizeValues(GrandientWeights,min_value,max_value)
        imageWeights = imageWeights + normalizeValue
        
    
    totalEdges = np.concatenate((imageEdges,columnEdges),axis=0)
    
    #finding the totalWeights
    totalWeights = np.concatenate((imageWeights,columnWeights),axis=None)
    return totalWeights,totalEdges

def normalizeValues(weights,min_value,max_value):
    #find oldMaxvalue and oldMinvalue
    oldMinValue = np.min(weights)
    oldMaxValue = np.max(weights)   
    #finding the normalize value
    normalizeValue = ((weights-oldMinValue) / (oldMaxValue-oldMinValue) * (max_value-min_value)) + min_value
    #print(normalizeValue)
    return normalizeValue

def getRegion(imageSize,topLayer,bottomLayer,topAddition,bottomAddition,InvalideIndices,correctBottomLine):

    InvalideIndices = np.int_(InvalideIndices)
    topLayer = np.array(topLayer)
    bottomLayer = np.array(bottomLayer)

    imageHeight = imageSize[0]
    imageWidth = imageSize[1]
    
    np.where(topLayer<0,0,topLayer)
    np.where(topLayer> imageHeight,imageHeight,topLayer)
    np.where(bottomLayer<0,0,bottomLayer)
    np.where(bottomLayer>imageHeight,imageHeight,bottomLayer)

#---------------------------------------------------------------------
#Expand the each layer boundary by the number of pixels to add,
#making sure to take care of any pixels that are out of bounds
#---------------------------------------------------------------------
    bottomLayer = bottomLayer + bottomAddition; 
    topLayer = topLayer + topAddition;   
#----------------------------------------------------------------------
# Limit the layers by the invalid region
#-----------------------------------------------------------------------
    invalidImage = np.zeros(imageHeight*imageWidth)
    invalidImage[InvalideIndices] = 1
    invalidImage = np.reshape(invalidImage,(imageHeight,imageWidth))

    for iCol in range(0,imageWidth):  
        t1 = np.array(np.where(invalidImage[:,iCol] == 0))
        
        topIndex = t1[0,0]  
        bottomIndex = t1[0,np.size(t1)-1]
        topLayer[iCol] = max(topLayer[iCol],topIndex)
        bottomLayer[iCol] = min(bottomLayer[iCol],bottomIndex)  
        
   # print(bottomLayer)
#----------------------------------------------------------------------
#Correct the appropriate line if it crosses the other line
#----------------------------------------------------------------------
    difference = np.subtract(bottomLayer,topLayer)
    invalidInd = np.where(difference < 0)
    if not invalidInd:
        print('invalidInd is empty')
    else:
        bottomLayer[invalidInd] = topLayer[invalidInd]
    
#----------------------------------------------------------------------
#  Get the indices of all pixels in between the two regions  
#----------------------------------------------------------------------
    regionImage = np.zeros([imageHeight*imageWidth]) 
   
    for iCol in range(0,imageWidth):
        if iCol < imageWidth-1:
            if topLayer[iCol] > bottomLayer[iCol+1]:
                topLayer[iCol] = topLayer[iCol+1]
                bottomLayer[iCol+1] = bottomLayer[iCol]
               
            elif (bottomLayer[iCol] < topLayer[iCol+1]):  
                bottomLayer[iCol] = bottomLayer[iCol+1]
                topLayer[iCol+1] = topLayer[iCol]
        
        yRegion = np.arange(topLayer[iCol],bottomLayer[iCol]+1) 
        yRegion = yRegion.astype('int')

        cols = iCol * np.ones(len(yRegion))
        cols = cols.astype('int')
        arr = (yRegion,cols)
       
        indices = np.ravel_multi_index(arr,(imageHeight,imageWidth), order='F')      
        regionImage[indices] = 1
        
#----------------------------------------------------------------------
#Take out any region indices that were specified as invalid
#----------------------------------------------------------------------
    invalidImage1 = np.zeros(imageHeight*imageWidth) 
    invalidImage1[InvalideIndices] = 1
    invalidImage = ((invalidImage1.astype('int')) & (regionImage.astype('int')))
    
# Remove invalid indices from the region
    regionImage[InvalideIndices] = 0
    
# Get the Indices
    regionIndices = np.where(regionImage == 1)
    return regionIndices

def cutRegion(imageSize,regionIndices,Edges,weightingMatrix):
    regionIndices = np.asarray(regionIndices).ravel()
    regionIndices = regionIndices.astype('int')
    
    imageWidth = imageSize[1]
    regionIndArr = np.zeros(imageSize[0]*imageSize[1])
    region = np.zeros(imageSize[0]*imageSize[1])

    #Mask Creation
    regionIndArr[regionIndices] = 1
    regionIndArr = np.array(regionIndArr,dtype = bool)
    
    #  Make sure the region spans the entire width of the image
    y,x = np.unravel_index([regionIndices],(imageSize[0],imageSize[1]),'F')
    startIndex = regionIndices[0]

    t1 = np.array(np.where(x == (imageWidth-1)))
    endIndex = t1[1,0]
 
    # Make sure the coordinate indices span the entire width of the image
    coordinateIndices = []
    
    if (len(coordinateIndices) == 0) or (coordinateIndices[0] > imageWidth):
        coordinateIndices = [startIndex]
        
    y,x = np.unravel_index(coordinateIndices,(imageSize[0],imageSize[1]))

    if (len(coordinateIndices) == 0) or (x < imageWidth):
        endIndex = regionIndices[endIndex]
        coordinateIndices = [coordinateIndices,endIndex]
   
    A = sparse.coo_matrix((weightingMatrix,(Edges[:,0],Edges[:,1])),shape=(imageSize[0]*imageSize[1],imageSize[0]*imageSize[1]))
    sparseMatrixT = csr_matrix(A)
    sparseMatrix = sparseMatrixT[regionIndArr][:,regionIndArr]

    #Dijkstra Shortest Path
    region = np.zeros(imageSize[0]*imageSize[1])
    region[regionIndices]=np.arange(0,len(regionIndices))

    firstIndex = coordinateIndices[0]
    secondIndex = coordinateIndices[-1]

    startIndex = int(region[firstIndex])
    endIndex = int(region[secondIndex])

    D, Pr =  dijkstra(sparseMatrix, directed=False, indices=0, return_predecessors=True)
    path = get_path(Pr,endIndex)
 
    y,x = np.unravel_index(regionIndices[path],(imageSize[0],imageSize[1]),order = 'F')
    cut = np.zeros(imageWidth)

    for column in range(0,imageWidth):
        if column == 0:
            t1 = np.array(np.where(x == column))
            index = t1[0,np.size(t1)-1]
        else:
            t1 = np.array(np.where(x == column))
            index = t1[0,0]
        cut[column] = y[index]
    return cut

#step 2.4.1
def get_path(Pr, j):
    path = [j]
    k = j
    
    while Pr[ k] != -9999:
        path.append(Pr[ k])
        k = Pr[ k]
    return path[::-1]


#Step 4: Resampling
def resampleLayers(layers):
    nLayers,layersLength =layers.shape
    layers = np.array(layers)
    
    newSize = (read_images.shape[1],read_images.shape[2])
    originalSize = (resized_images.shape[1],resized_images.shape[2])

    #Scaling to upsampling
    scale = np.divide(newSize,originalSize)

    #Upsample in the Y direction
    layers = np.round(layers * scale[0])

#----------------------------------------------------------------------
#Upsample each layer in the x direction using interpolation
#----------------------------------------------------------------------
    #nLayers = 4
    newWidth = newSize[1]
    x = np.array(range(0,newWidth))
    y = np.array(layers)
    
    layers = np.empty((nLayers,newWidth))
    layers[:] = np.NaN
    ind = np.round(np.arange(0,newWidth,scale[1]))
    ind = ind.astype('int')
    ind[-1] = newWidth-1
    layers[:,ind] = y
    
   
    #print(layers.shape)
    for iLayer in range(0,nLayers):
        layer = layers[iLayer,:]
    
        validInd = np.argwhere(~np.isnan(layer))
        invalidInd = np.argwhere(np.isnan(layer))
    
        temp = np.copy(layer)
        temp[validInd] = 1
        validIndArr = np.where(temp == 1,1,0)
    
        temp1 = np.copy(layer)   
        temp1[invalidInd] = 1
        invalidIndArr = np.where(temp1 == 1,1,0)
    
        t1 = np.array(np.where(invalidIndArr == 0))
        val = t1[0,0]
        invalidIndArr[0:val] =0 
        val1 = t1[0,-1]
        invalidIndArr[val1:-1] =0 
    
        #Interpolation
        tck = interpolate.splrep(validInd,layer[validInd])
        layer[invalidInd] = interpolate.splev(invalidInd, tck)
   
        #print(layer.shape)
        #Make sure the layers do not cross
        if iLayer > 0:
            diffVal = layer - layers[iLayer-1,:]
            invInd = np.where(diffVal < 0)
            layer[invInd] = layers[iLayer-1,invInd]
        layers[iLayer,:] = np.round(layer)
    
    return layers

def normal_graphCut(image,axialRes,laterRes,rpeTop,rpeBottom,invalidIndices,recalculateWeights):
    
    image = normalizeValues(image,0,1)
    imageHeight = image.shape[0]
    
    image = addColumns(image, 1)
    
    rpeTop = addColumns(rpeTop, 1)
    rpeBottom = addColumns(rpeBottom, 1)
     
    invalidIndices = invalidIndices[0] + imageHeight
    
    #rpeTop = rpeTop.ravel()
    #rpeBottom = rpeBottom.ravel()
    
    maxIndex = 0
    #LAYER_INDICES = [0,7,7,6]
    LAYER_INDICES  = [0,7,7,6,5,3,2,4,3,1]
    layerIndices = np.array(LAYER_INDICES)
    
    #MATRIX_INDICES = [0,1,2,4]
    MATRIX_INDICES = [0,1,2,4,4,4,3,3,4,5]
    matrixIndices = np.array(MATRIX_INDICES)
    
    uniqueLayerIndices, index = np.unique(layerIndices, return_index=True)
    uniqueLayerIndices = uniqueLayerIndices[index.argsort()]
    
    for index in range(0,numLayers):
        lastIndex = np.array(np.where(layerIndices == uniqueLayerIndices[index]))
        lastIndex = lastIndex[-1,0]
        
        if bool(lastIndex) & (lastIndex > maxIndex):
            maxIndex = lastIndex
            
    if maxIndex > 0:
        layerIndices = layerIndices[0:maxIndex+1]
        
        if bool(matrixIndices.all):
            matrixIndices = matrixIndices[0:maxIndex+1]
            
    #------------------------------------------------------------------
    #  Generate a weighting matrix for the image
    #------------------------------------------------------------------
    if recalculateWeights:
        weightingMatrices,edges = normal_weightingMatrix(image,axialRes,lateralRes,matrixIndices,invalidIndices) 
    
    imageSize = image.shape
    nLayers = max(layerIndices)
    layers = np.zeros([8, imageSize[1]])
   
    layers[:,:] = np.nan
   
    #foveaParams = {'Index':0, 'Range':0, 'Percentage':0}
    Index = 0
    Range = 0
    Percentage = 0
    
    #Loop through Each layer to segment
    for iLayer in range(0,len(layerIndices)):
    #for iLayer in range(0,1):
        layerIndex = layerIndices[iLayer]
        #Get parameters for the current layer to segment-Normal GraphCut Region
        eye =1
       
        regionIndices = normal_getGraphCutRegion(image, layerIndex, axialRes, eye,Index,Range, rpeTop, rpeBottom,layers)
        matrixIndex = matrixIndices[iLayer]
        weightMatrix = weightingMatrices[matrixIndex]
        
        #Cut Region
        cut = cutRegion(imageSize, regionIndices,edges, weightMatrix)
        if iLayer == 0:
            cut_1 = cut
        
        #Fovea Region
        if layerIndex == 2:
            ilm = layers[0,:].astype('int')
            
            innerLayer = np.round(savgol_filter(cut,251,2))
            
            rpe = layers[5,:].astype('int')
           
            Index,Range,Percentage = locateFovea(imageSize, axialRes, lateralRes, ilm, innerLayer, rpe, invalidIndices) 
            
        layers[layerIndex,:] = cut
    layers[0,:] = cut_1
    for iLayer in range(0,nLayers+1):
        if iLayer < nLayers:
            topLayer = layers[iLayer,:]
            bottomLayer = layers[iLayer+1,:]
            crossIndices = np.array(np.where((bottomLayer - topLayer) < 0))
                
            bottomLayer[crossIndices] = topLayer[crossIndices]
            layers[iLayer+1,:] = bottomLayer
     # Remove the extra columns and layers 
    layers = layers[:,1:-1]
    # Remove extra layers that were not segmented or supposed to be
    # segmented
    layersToRemove = np.setdiff1d(np.arange(0,nLayers+1),uniqueLayerIndices)
    layers = np.delete(layers,(layersToRemove),axis=0)
    
    #layers = cut[1:-1]
    return layers

def normal_weightingMatrix(image,axialRes,lateralRes,matrixIndices,invalidIndices):

    imageSize = image.shape
    imageHeight = imageSize[0]
    imageWidth = imageSize[1]
    
    edges = createLattice(imageSize)
    #np.savetxt('edges.txt',edges,delimiter=' ',fmt='%d')
    
    maxIndex = imageHeight*imageWidth
    
    leftColIndices = np.arange(0,imageHeight-1)
    rightColIndices = np.arange(((imageHeight-1)*(imageWidth-1)), maxIndex)
    
    columnIndices = np.concatenate((leftColIndices,rightColIndices),axis=0)
    
    imageIndices = np.setdiff1d((np.arange(0,edges.shape[0])), columnIndices)
    columnEdges = edges[columnIndices,:]
    imageEdges = edges[imageIndices,:]
    
    xFilterSize = round(X_FILTER_SIZE / lateralRes)
    yFilterSize = round(Y_FILTER_SIZE / axialRes)
    
    kernel = fspecial_gauss2d((xFilterSize,yFilterSize),SIGMA)
    smoothImage = blurImage(image,kernel)
    kernel = fspecial_gauss2d((1,xFilterSize),SIGMA)
    smoothImage2 = blurImage(image,kernel)
    
    lightDarkEdgeImage = (blurImage(smoothImage, -EDGE_FILTER) > 0) * blurImage(smoothImage, -EDGE_FILTER)
    lightDarkEdgeImage = np.abs(lightDarkEdgeImage)
    darkLightEdgeImage = (blurImage(smoothImage, EDGE_FILTER) > 0) * blurImage(smoothImage, EDGE_FILTER)
    darkLightEdgeImage = np.abs(darkLightEdgeImage)
    lightDarkEdgeImage2 = (blurImage(smoothImage2, -EDGE_FILTER) > 0) * blurImage(smoothImage2, -EDGE_FILTER)
    lightDarkEdgeImage2 = np.abs(lightDarkEdgeImage2)
    darkLightEdgeImage2 = (blurImage(smoothImage2, EDGE_FILTER) > 0) * blurImage(smoothImage2, EDGE_FILTER)
    darkLightEdgeImage2 = np.abs(darkLightEdgeImage2)
    
   
    darkLightInd = (darkLightEdgeImage > 0)
    lightDarkInd = (lightDarkEdgeImage > 0)
    darkLightInd2 = (darkLightEdgeImage2 > 0)
    
    darkLightEdgeImage[lightDarkInd] = 0
    lightDarkEdgeImage[darkLightInd] = 0
    lightDarkEdgeImage2[darkLightInd2] = 0
    
    lightDarkEdgeImage = normalizeValues(lightDarkEdgeImage,0,1)
    darkLightEdgeImage = normalizeValues(darkLightEdgeImage,0,1)
    lightDarkEdgeImage2 = normalizeValues(lightDarkEdgeImage2,0,1)
    lightDarkEdgeImage3 = lightDarkEdgeImage
    
    for iCol in range(0,imageWidth):
        column = darkLightEdgeImage[:,iCol]
        column = np.array(column)
        maxima = np.where(np.diff(np.sign(np.diff(column,n=1,axis=-1,append=0))) < 0)
        maxima = maxima[0]
        darkLightEdgeImage[:,iCol] = 0
        darkLightEdgeImage[maxima,iCol] = column[maxima]

        column = lightDarkEdgeImage[:,iCol]
        column = np.array(column)
        maxima = np.where(np.diff(np.sign(np.diff(column,n=1,axis=-1,append=0))) < 0)
        maxima = maxima[0]
        lightDarkEdgeImage[:,iCol] = 0
        lightDarkEdgeImage[maxima,iCol] = column[maxima]
  
    darkLightEdgeImage[lightDarkInd] = -1
    lightDarkEdgeImage[darkLightInd] = -1
    
    darkLightEdgeImage = darkLightEdgeImage.ravel(order='F')
    darkLightEdgeImage[invalidIndices] = 0
    lightDarkEdgeImage = lightDarkEdgeImage.ravel(order='F')
    lightDarkEdgeImage[invalidIndices] = 0
    lightDarkEdgeImage2 = lightDarkEdgeImage2.ravel(order='F')
    lightDarkEdgeImage2[invalidIndices] = 0
    lightDarkEdgeImage3 = lightDarkEdgeImage3.ravel(order='F')
    lightDarkEdgeImage3[invalidIndices] = 0
    
    darkLightGradientWeights = 2 - darkLightEdgeImage[imageEdges[:,0]] - darkLightEdgeImage[imageEdges[:,1]]
    lightDarkGradientWeights = 2 - lightDarkEdgeImage[imageEdges[:,0]] - lightDarkEdgeImage[imageEdges[:,1]]
    lightDarkGradientWeights2 = 2 - lightDarkEdgeImage2[imageEdges[:,0]] - lightDarkEdgeImage2[imageEdges[:,1]]
    lightDarkGradientWeights3 = 2 - lightDarkEdgeImage3[imageEdges[:,0]] - lightDarkEdgeImage3[imageEdges[:,1]]
    
    smoothImage = smoothImage.ravel(order='F')
    smoothImage[invalidIndices] = 0
    
    brightIntensityWeights = - smoothImage[imageEdges[:,0]] - smoothImage[imageEdges[:,1]]
    darkIntensityWeights = smoothImage[imageEdges[:,0]] + smoothImage[imageEdges[:,1]]

    [yFirstPoint, xFirstPoint] = np.unravel_index(imageEdges[:,0],imageSize,order='F')
    [ySecondPoint, xSecondPoint] = np.unravel_index(imageEdges[:,1],imageSize,order='F')
    distanceWeights = np.sqrt((xFirstPoint - xSecondPoint) ** 2 + (yFirstPoint - ySecondPoint) ** 2)

    weights = ([(darkLightGradientWeights)],(brightIntensityWeights,distanceWeights),
               (lightDarkGradientWeights2,distanceWeights),
               (lightDarkGradientWeights3,distanceWeights),
               (darkLightGradientWeights,distanceWeights),
               (lightDarkGradientWeights,darkIntensityWeights,distanceWeights))
    
    nMatrices = len(weights)
    matrixIndices1 = (matrixIndices > 0)
    matrixIndices = matrixIndices[matrixIndices1]
    matrixIndices1 = (matrixIndices < nMatrices+1)
    matrixIndices = matrixIndices[matrixIndices1]
    weightingMatrices = []
    matrixSize = maxIndex
    
    matrixIndices1 = np.array([0,1,2,3,4,5])
    
    for iMatrix in range(0,len(weights)):
        matrixIndex = matrixIndices1[iMatrix]
        weightingMatrices1,edges = generateWeightingMatrix(matrixSize,imageEdges,weights[iMatrix],columnEdges,MIN_WEIGHTS)
        weightingMatrices.append(weightingMatrices1)

    return weightingMatrices,edges


def fspecial_gauss2d(shape,sigma):
    m,n = [(ss-1.)/2. for ss in shape]
    y,x = np.ogrid[-m:m+1,-n:n+1]
    h = np.exp( -(x*x + y*y) / (2.*sigma*sigma) )
    h[ h < np.finfo(h.dtype).eps*h.max() ] = 0
    sumh = h.sum()
    if sumh != 0:
        h /= sumh
    return h

def blurImage(image,filter1):
    [imageHeight, imageWidth] = image.shape
    filterSize = filter1.shape
    
    yHW = round(filterSize[0]/2)
    xHW = round(filterSize[1]/2)
    
    image1 = cv2.copyMakeBorder(image, 0, yHW, 0, xHW, cv2.BORDER_CONSTANT)
    image1[yHW:imageHeight+yHW+1,xHW:imageWidth+xHW+1] = image
    
    rows_to_added = image1[imageHeight-1:imageHeight+yHW-1,:]
    rows_to_added = np.flip(rows_to_added,axis=0)
    image1 = np.vstack ((image1, rows_to_added))
    rows_to_changed = image1[yHW+1:2*yHW+1,:]
    rows_to_changed = np.flip(rows_to_changed,axis=0)
    image1[0:yHW,:] = rows_to_changed
    
    columns_to_added = image1[:,imageWidth-1:imageWidth+xHW-1]
    columns_to_added = np.flip(columns_to_added,axis=1)
    image1 = np.hstack ((image1, columns_to_added))
    columns_to_changed = image1[:,xHW+1:2*xHW+1]
    columns_to_changed = np.flip(columns_to_changed,axis=1)
    image1[:,0:xHW] = columns_to_changed
    
    image1 = signal.convolve2d(image1, filter1, boundary='symm', mode='same')
    image1 = image1[yHW:imageHeight+yHW,xHW:imageWidth+xHW]
    return image1

def normal_getGraphCutRegion(image, layersNumber, axialRes, eye,Index,Range, rpeTop, rpeBottom, layers):
    imageSize = image.shape
    
    imageHeight = imageSize[0]
    imageWidth = imageSize[1]
    
    topLayerAddition = 0
    bottomLayerAddition = 0
    correctBottomLine = 0

        #vitreous-NFL
    if layersNumber == 0:
        yTop = np.zeros([imageWidth])
        yBottom = rpeTop
        correctBottomLine = 1

        #cut RPE-Choroid   
    elif layersNumber ==7:
        if np.all(np.isnan(layers[7,:])):
            if np.all(np.isnan(rpeTop)):
                yTop = layers[0,:] + np.round(100.5/axialRes)
            else:
                yTop = rpeTop
                yBottom = rpeBottom
        else:
            yTop = layers[7,:] + np.round(13.4/axialRes)
            yBottom = layers[7,:] + np.round(67/axialRes)
     
    #cut OS-RPE
    elif layersNumber == 6:
        yTop = layers[7,:] - np.round(33.5/axialRes)
        yBottom = layers[7,:] - np.round(13.4/axialRes)
        
        
    elif layersNumber == 5:
        yTop = layers[6,:] - np.round(67/axialRes);
        yBottom = layers[6,:] - np.round(20.1/axialRes);


    elif layersNumber == 3:
        if np.all(np.isnan(layers[4,:])):
            difference = layers[5,:] - layers[0,:]
            yTop1 = layers[0,:] + np.round(difference/3)
            yTop2 = layers[5,:] - np.round(134/axialRes)
            yTop3 = layers[0,:] + np.round(13.4/axialRes)
            yTop = np.maximum(np.minimum(yTop1,yTop2),yTop3)
            yBottom = layers[5,:] - np.round(40.2/axialRes) 
        else:
            yTop = layers[2,:]
            yBottom = layers[4,:]
            correctBottomLine = 1        

    elif layersNumber == 2:
        yTop = layers[3,:] - np.round(46.9/axialRes)
        yBottom = layers[3,:]

    elif layersNumber == 4:
        a = savgol_filter(layers[3,:],251, 2)
        yTop =np.round(np.transpose(a))
        yBottom1 = yTop + np.round(100.5/axialRes)
        yBottom2 = layers[5,:] - np.round(13.4/axialRes)
        yBottom = np.minimum(yBottom1,yBottom2)
    
        if bool(Index):
            Index = int(Index)
            range1 = np.arange(Range[0],Index)
            yFovea = layers[2,Index] - np.round(13.4/axialRes)
            thickness = np.arange(0,len(range1))
            thickness = np.round((yFovea-yTop[range1[0]])/len(range1) * thickness)
            yTop[range1] = yTop[range1[1]] + thickness
            range1 = np.arange(Index,Range[1])
            yFovea = layers[2,Index] - np.round(13.4/axialRes)
            thickness = np.arange(0,len(range1))
            thickness = np.round((yTop[range1[-1]]-yFovea)/len(range1) * thickness)
            yTop[range1] = yFovea + thickness


            
    elif layersNumber == 1:
        yTop =layers[0,:]
        yBottom = layers[2,:] -np.round(26.8/axialRes)

        if bool(Index):
            range1 = np.arange(Range[0],Range[1])
            yBottom[range1] = layers[0,range1] + np.round(20.1/axialRes)

            if eye == 1:
                thinRange = np.arange(range1[-1],imageWidth)
                thickRange =np.arange(0,range1[0])
            elif eye == 2:
                thinRange = np.arange(0,range1[1])
                thickRange =np.arange(range1[-1],imageWidth)
            thickness =np.arange(0,len(thickRange))
            thickness = np.round(np.round(33.5/axialRes) / len(thickRange) * thickness)
            yTop[thickRange] = yTop[thickRange] + thickness
            yBottom[thickRange] = layers[2,thickRange] - (thickness)
            yBottom[thinRange] = yTop[thinRange] + np.round(26.8/axialRes)
            correctBottomLine = 1
        else:
            range1 = np.arange(0,imageWidth)
            if eye == 1:
                range1 = range1[::-1]
            thickness = np.arange(0,len(range1))
            thickness = np.round(np.round(13.4/axialRes) / len(range1) * thickness)
            yTop[range1] = yTop[range1] + thickness
    else:
        print('Segmentation of layer %d is not supported', layerNumber)

    #Handle cases where the input layer is NaN or empty.

    nanIndices = np.isnan(yTop)

    if np.sum(nanIndices) > 0:
        yTop[nanIndices] = np.ones([np.sum(nanIndices)])

    nanIndices = np.isnan(yBottom)
    if np.sum(nanIndices) > 0:
        yBottom[nanIndices] = imageHeight*np.ones([np.sum(nanIndices)]);

    #Make the region smaller with respect to the selected minimum distance between lines
    yTop = yTop.ravel()
    yBottom = yBottom.ravel()
    regionIndices = getRegion(imageSize,yTop,yBottom,topLayerAddition,bottomLayerAddition,[],correctBottomLine)       
    regionIndices = np.array(regionIndices)
    return regionIndices

def locateFovea(imageSize,axialRes,lateralRes,ilm, innerLayer, rpe,invalidIndices):
    imageWidth = imageSize[1]
    
    margin = round(imageWidth/8)

    # create the zeros array
    middleInd = np.zeros((imageWidth), dtype=np.int)
    middleInd[margin-1:imageWidth-margin] = 1

    # find intersect value
    x = np.arange(imageWidth)

    invalidInd = np.intersect1d(np.ravel_multi_index((np.hstack((ilm,rpe)),np.hstack((x,x))),imageSize,order='F'),invalidIndices,assume_unique=False,return_indices=False)
    yInvalid,xInvalid  = np.unravel_index(invalidInd,imageSize,order='F')
    xInvalid = np.unique([xInvalid])
    middleInd[xInvalid] = 0

    # using the filter
    thicknessOrig = innerLayer - ilm
    thicknessOrig = thicknessOrig.reshape(1,thicknessOrig.shape[0])

    # thicknessOrig = np.array(thicknessOrig)
    thickness = savgol_filter(thicknessOrig,21,2)
    # find the difference and sign value
    midIndValue = middleInd[1:].T
    thickness = thickness.T
    out = np.diff(np.sign(np.diff(np.vstack([thickness[0],thickness]).ravel(order='F'))),axis=0)
   
    # calculate the maxima & minima value using np.where
    midIndValue = midIndValue.ravel(order = 'F')
    maxima = np.where((midIndValue) & (out < 0))
    maxima = maxima[0]
  
    # maxima_temp = maxima[np.where((np.diff(maxima))==1)] 
    maxima_New = np.delete(maxima,np.where((np.diff(maxima))==1))

    minima =  np.where((midIndValue) & (out > 0))
    minima = minima[0]

    # minima_temp = minima[np.where((np.diff(minima))==1)] 
    minima_New = np.delete(minima,np.where((np.diff(minima))==1))


    # create the zeros and ones
    combined1 = np.hstack((np.vstack((maxima_New,np.zeros((len(maxima_New))))),np.vstack((minima_New,np.ones((len(minima_New)))))))

    # sorting the array
    values = pd.DataFrame(combined1).sort_values(by=0, axis=1)
    combined = (values.values).astype("int")

    # find the fovea location
    difference = np.abs(np.diff(np.hstack(thickness[combined[0,:].astype(int)])))
    locations = np.where(difference>round(33.5/axialRes))
    locations = locations[0]
    # Look for the largest change in thickness (corresponding to the fovea location)
    Index = []
    Range = []
    Percentage = []

    for index in range(len(locations)-1):
        if ((((combined[1,locations[index]] == 0) and (combined[1,locations[index]+1] == 1))) and (((combined[1,locations[index+1]] == 1) and (combined[1,locations[index+1]+1] == 0)))):
            foveaRange = [combined[0,locations[index]], combined[0,locations[index+1]+1]]
            thicknessOrig = thicknessOrig.flatten(order='F')
            foveaThick = thicknessOrig[int(foveaRange[0]):int(foveaRange[1])]
            foveaIndex = np.where(foveaThick == min(foveaThick))
            foveaIndex = foveaIndex[0]
            foveaIndex = foveaIndex[round(len(foveaIndex)/2)] + foveaRange[0] - 1

        # flattening the innerlayer,ilm and rpe        
            innerLayer = innerLayer.flatten(order='F')
            ilm = ilm.flatten(order='F')
            rpe = rpe.flatten(order='F')
            foveaPercentage = (innerLayer[foveaIndex.astype(int)] - ilm[foveaIndex.astype(int)]) / (rpe[foveaIndex.astype(int)] - ilm[foveaIndex.astype(int)])

        # Make the fovea range a constant width        
            thickness = round(670/lateralRes)
            foveaRange[0] = np.max((1,foveaIndex-thickness))
            foveaRange[1] = np.min((imageWidth,foveaIndex + thickness))

        # print index,range and percentage values
            Index = foveaIndex
            Range = foveaRange
            Percentage = foveaPercentage
            
    return Index,Range,Percentage

def normal_FlattenImage(image,line):
    #Get image size
    
    imageHeight,imageWidth = image.shape
    #Get the Line to Flatten
    #Extrapolate missing values from the line
    x = np.array(range(0,imageWidth))
    validInd = ~np.isnan(line)
    line = savgol_filter(line,251,2)
    line = line.ravel(order='F')

    # Interpolation
    line = (interpolate.interp1d(x[validInd.ravel(order='F')],line[validInd.ravel(order='F')],kind = 'nearest',fill_value='extrapolate'))
    
    line = line(x)
    line = np.ceil(line)
  
    # make sure line is not out of Image bounds
    line[line < 0] = 0
    line[line > imageHeight-1] = imageHeight-1
    
    # Flatten the image based on the line
    flattenedImage,pixelShift,invalidIndices,flattenedLine = flattenImage(image,line)
    return flattenedImage,pixelShift,invalidIndices

def flattenImage(image,lineToFlatten):
    
    referencePoint =0
    fillType = 1
    flattenedImage = image
    imageHeight, imageWidth = image.shape
    invalidImage = np.zeros(image.shape)
    invalidIndices = []
    mirroredColumn = []
    
    if imageHeight == 1:
        reference = round(statistics.mean(lineToFlatten))
        pixelShift = reference - lineToFlatten
        pixelShift = pixelShift.reshape(1,resizedImageWidth)
        flattenedImage = image + pixelShift
        invalidIndices = []
        flattenedLine =  reference * np.ones(image.shape)
        
    else:
        reference = round(statistics.mean(lineToFlatten))

        pixelShift = reference - lineToFlatten
        #pixelShift = scipy.io.loadmat('pixelShift')
       # pixelShift = pixelShift["pixelShift"]
        pixelShift = pixelShift.astype('int')
        #pixelShift = pixelShift.ravel()
        #print(pixelShift.shape)
       

        for index in range(0,len(lineToFlatten)):
            image_new = np.reshape(image[:,index],(resizedImageHeight,))
            flattenedImage[:,index] =np.roll(image_new,pixelShift[index])

            # If shifted down
            if pixelShift[index] > 0:
                 # Get locations where pixels have been shifted out. These
                 #are invalid regions that need to be replaced
                invalidIndices =np.arange(0,pixelShift[index])

                 # Get the mirror image of the valid regions of the column,
                 #which will be used to replace the invalid regions
                mirroredColumn = np.pad(flattenedImage[invalidIndices[-1]:,index],(len(invalidIndices),0),'symmetric')         
                mirroredColumn = mirroredColumn[0:len(invalidIndices)]

             # If shifted up
            elif pixelShift[index] < 0:
                 # Get locations where pixels have been shifted out. These
                 # are invalid regions that need to be replaced  
                invalidIndices = np.arange(imageHeight + pixelShift[index],imageHeight)
                mirroredColumn = np.pad(flattenedImage[0:invalidIndices[0],index],(0,len(invalidIndices)),'symmetric') 
                mirroredColumn = mirroredColumn[-len(invalidIndices):,]
            else: 
                invalidIndices = []
                mirroredColumn = []
             #Replace the invalid indices with the mirror image of the
             #valid pixels. This is so that there is no artificial gradient
             #created when segmenting the image later on.

            flattenedImage[invalidIndices, index] = mirroredColumn
             #Keep track of which indices on the image are invlaid 
            invalidImage[invalidIndices, index] = 1

     #Get the indices of the invalid regions
    invalidImage = invalidImage.ravel(order = 'F')
    invalidIndices = np.where(invalidImage == 1)
    
    #Get the resulting flattened line
    flattenedLine = lineToFlatten + pixelShift
    return flattenedImage,pixelShift,invalidIndices,flattenedLine

def cart2pol(x, y):
    rho = np.linalg.norm([x,y])
    phi = np.arctan2(y, x)
    return(rho, phi)

#Read Tif Image 
read_images = []
resized_images = []
dirName = sys.argv[1]
path = glob.glob(dirName+'/*.tif')

for file in path:
    inputImage = cv2.imread(file,0)
    read_images.append(inputImage)
    #medianBlurImage = cv2.medianBlur(inputImage,3)
    inputImageHeight,inputImageWidth = inputImage.shape

    #X & Y Scale for Resized Image
    xResizeScale = LATERAL_RESOLUTION / X_RESOLUTION
    yResizeScale = AXIAL_RESOLUTION / Y_RESOLUTION

    #Find width & height of Rescaled Image
    width = math.ceil(inputImage.shape[1]*xResizeScale)
    height = math.ceil(inputImage.shape[0]*yResizeScale)

    # Resized Image
    dim = (width,height)

    resizedImage = cv2.resize(inputImage,dim,interpolation=cv2.INTER_NEAREST)
    resized_images.append(resizedImage)
    
read_images = np.array(read_images)
resized_images = np.array(resized_images)

rpe = []
ilm = []
gcc = []

ctr = 1

for i in range(0,read_images.shape[0],5):
    inputImage = resized_images[i]
    resizedImageHeight,resizedImageWidth = inputImage.shape

    # normal Get BW Image
    bwImage = normal_getBWImage(inputImage)
    borders = normalgetBorders(bwImage)
    borders = np.sort(borders,axis=0)
    
    rpeTop = borders[2,:]
    rpeTop[-1] = rpeTop[-2]
    
    rpeBottom = borders[3,:]
    rpeBottom[-1] = rpeBottom[-2]
    
    [flattenedImage,pixelShift,invalidIndices] = normal_FlattenImage(inputImage,rpeTop)
   
    #Reshape Array
    rpeTop1 = rpeTop.reshape(1,rpeTop.shape[0])
    rpeBottom1 = rpeBottom.reshape(1,rpeBottom.shape[0])

    rpeTop2,_,_,_ = flattenImage(rpeTop1,-pixelShift)
    rpeBottom2,_,_,_ = flattenImage(rpeBottom1,-pixelShift)
    
    layers1 = normal_graphCut(flattenedImage,axialRes,lateralRes,rpeTop2,rpeBottom2,invalidIndices,1)
    
    a = np.array([0,2,6])
    layers1 = layers1[a]
    #smoothing = [155,155,499,499,499,499,499,499]
    smoothing = [601,601,749]

    layer_PerImage = []
    for j in range(0,layers1.shape[0]):
        iLayer = layers1[j,:]
        iLayer = iLayer.reshape(1,len(iLayer))
        layerEach,_,_,_ = flattenImage(iLayer,pixelShift)
        
        #Resample & Smooth Layers
        resampledlayers = resampleLayers(layerEach)
        y_filtered = savgol_filter(resampledlayers,smoothing[j], 2)
       
        layer_PerImage.append(np.round(y_filtered.ravel(order='F')))
        
    np.savetxt(sys.argv[2]+"/Data%04d.csv"%ctr,layer_PerImage,delimiter=' ',fmt='%d')
    
    rpe.append(layer_PerImage[2])
    ilm.append(layer_PerImage[0])
    gcc.append(layer_PerImage[1])
    ctr = ctr + 1
    
mid=(rpe[0]-ilm[0])/2
inl=rpe-mid
mid2=(inl[0]-ilm[0])/2
gcc=inl-mid2
ilm_layer=np.array(ilm)
gcc_layer=np.array(gcc)

ilmthickness=rpe-ilm_layer
gccthickness=gcc-ilm_layer

np.savetxt(sys.argv[2]+"/ilmthickness.csv",ilmthickness,delimiter=',',fmt='%d')
np.savetxt(sys.argv[2]+"/gccthickness.csv",gccthickness,delimiter=',',fmt='%d')

rpe_layer=np.array(rpe)

nRadialScans=6
nAscans=2000

ilm_l=ilm_layer.reshape([nRadialScans,-1])
rpe_l=rpe_layer.reshape([nRadialScans,-1])
gcc_l=gcc_layer.reshape([nRadialScans,-1])
ilm_l=np.concatenate((ilm_l[:,nAscans//2:],np.flip(ilm_l[:,:nAscans//2:],1)))
ilm_l=np.concatenate((ilm_l, ilm_l[0,:].reshape(1,-1)))
rpe_l=np.concatenate((rpe_l[:,nAscans//2:],np.flip(rpe_l[:,:nAscans//2:],1)))
rpe_l=np.concatenate((rpe_l,rpe_l[0,:].reshape(1,-1)))
gcc_l=np.concatenate((gcc_l[:,nAscans//2:],np.flip(gcc_l[:,:nAscans//2:],1)))
gcc_l=np.concatenate((gcc_l, gcc_l[0,:].reshape(1,-1)))
rho_s = np.arange(1, nAscans//2+1)
phi_s = np.linspace(-math.pi, math.pi, 2*nRadialScans+1)
f_thick = interpolate.interp2d(rho_s, phi_s, rpe_l-ilm_l, kind='cubic', fill_value=np.nan)
g_thick = interpolate.interp2d(rho_s, phi_s, gcc_l-ilm_l, kind='cubic', fill_value=np.nan)

dsample=10 # change this to 1 to generate a map in original size, i.e. 2000 x 2000, will be slow if not usign c++

thickchartilm = np.zeros([nAscans//dsample,nAscans//dsample])
thickchartgcc= np.zeros([nAscans//dsample,nAscans//dsample])

outputFolder = sys.argv[2]

for x in range(0,nAscans,dsample):
    for y in range(0,nAscans,dsample):
        xi= x-nAscans//2
        yi= y-nAscans//2
        rho, phi = cart2pol(xi,yi)
        thickchartilm[y//dsample, x//dsample]=f_thick(rho,phi)
        thickchartgcc[y//dsample, x//dsample]=g_thick(rho,phi)
        
center=2000/2
start=0
end=2000
inner=333
outer=500

outerT=np.mean((ilmthickness[5][start:outer])+(ilmthickness[0][start:outer])+(ilmthickness[1][start:outer]))/3
outerI=np.mean((ilmthickness[2][start:outer])+(ilmthickness[3][(outer*3):end])+(ilmthickness[4][(outer*3):end]))/3
outerN=np.mean((ilmthickness[5][(outer*3):end])+(ilmthickness[0][(outer*3):end])+(ilmthickness[1][(outer*3):end]))/3
outerS=np.mean((ilmthickness[2][(outer*3):end])+(ilmthickness[3][start:outer])+(ilmthickness[4][start:outer]))/3

InnerT=np.mean((ilmthickness[5][outer:(outer+inner)])+(ilmthickness[0][outer:(outer+inner)])+(ilmthickness[1][outer:(outer+inner)]))/3
InnerI=np.mean((ilmthickness[2][outer:(outer+inner)])+(ilmthickness[3][((inner*2)+outer):(outer+(inner*3))])+(ilmthickness[4][((inner*2)+outer):(outer+(inner*3))]))/3
InnerN=np.mean((ilmthickness[5][((inner*2)+outer):(outer+(inner*3))])+(ilmthickness[0][((inner*2)+outer):(outer+(inner*3))])+(ilmthickness[1][((inner*2)+outer):(outer+(inner*3))]))/3
InnerS=np.mean((ilmthickness[2][((inner*2)+outer):(outer+(inner*3))])+(ilmthickness[3][outer:(outer+inner)])+(ilmthickness[4][outer:(outer+inner)]))/3

for i in range(5):
    fovea=np.mean(ilmthickness[i][(outer+inner):(outer+(inner*2))])
    


inn=834
out=1166
seg1=np.mean((gccthickness[5][start:inn])+(ilmthickness[1][start:inn]))/2
seg2=np.mean((gccthickness[1][start:inn])+(ilmthickness[2][start:inn]))/2
seg3=np.mean((gccthickness[2][start:inn])+(ilmthickness[4][out:end]))/2
seg4=np.mean((gccthickness[4][out:end])+(ilmthickness[5][out:end]))/2

seg5=np.mean((gccthickness[5][out:end])+(ilmthickness[1][out:end]))/2
seg6=np.mean((gccthickness[1][out:end])+(ilmthickness[2][out:end]))/2
seg7=np.mean((gccthickness[2][out:end])+(ilmthickness[4][start:inn]))/2
seg8=np.mean((gccthickness[5][start:inn])+(ilmthickness[5][start:inn]))/2  

thicknessvalues=np.array([outerT,outerI,outerN,outerS,InnerT,InnerI,InnerN,InnerS,fovea,
                          seg1,seg2,seg3,seg4,seg5,seg6,seg7,seg8])

fig1=plt.imshow(thickchartilm)
plt.axis('off')
fig1.axes.get_xaxis().set_visible(False)
fig1.axes.get_yaxis().set_visible(False)
plt.savefig(sys.argv[2]+'/ilmTorpeThickness.png',bbox_inches='tight')

fig2=plt.imshow(thickchartgcc)
plt.axis('off')
fig2.axes.get_xaxis().set_visible(False)
fig2.axes.get_yaxis().set_visible(False)
plt.savefig(sys.argv[2]+'/ilmTogccThickness.png',bbox_inches='tight')
#plt.imsave(outputFolder+'ilmTorpeThickness.png',thickchartilm)
#plt.imsave(outputFolder+'ilmTogccThickness.png',thickchartgcc)

with open(sys.argv[2]+'/ThicknessValue.csv', 'w', encoding='UTF8',newline='') as Thickness:
    writer1 = csv.writer(Thickness)
    writer1.writerow(thicknessvalues)